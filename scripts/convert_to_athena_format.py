#!/usr/bin/env python3
"""
Convert Synthea FHIR Bundle from UUID-based IDs to athenaHealth alphanumeric test format.

This script:
1. Maps all UUIDs to sequential alphanumeric IDs with 't' prefix (t1000000, t1010000, etc.)
2. Converts all resource IDs to alphanumeric test IDs (HAPI FHIR compatible)
3. Updates all resource references throughout the bundle
4. Adds athenaHealth-specific extensions (practice, chart-sharing-group, athenaId)
5. Adds metadata (versionId, lastUpdated, source, security tags)
6. Adds identifiers with system and value
7. Marks specified encounters as virtual (class: VR)
8. Adds pharmacy notes to MedicationRequests
9. Processes CCDA XML file and updates all UUID references to alphanumeric test IDs
10. Extracts and saves shared resources (Organization, Practitioner, Location) as transaction bundles

Usage:
    python3 convert_to_athena_format.py \\
        --input output/fhir/generated_patient.json \\
        --output output/fhir/athena_patient_1000000.json \\
        --patient-id 1000000 \\
        --practice-id a-16349
"""

import json
import argparse
import re
import os
import random
from datetime import datetime
from typing import Dict, List, Any, Tuple
import xml.etree.ElementTree as ET

# ID Range allocation for different resource types
# Using VERY LARGE ranges with high-entropy random selection to prevent 409 conflicts
# IDs are prefixed with letters to comply with HAPI FHIR requirement:
# "clients may only assign IDs which contain at least one non-numeric character"
# Ranges expanded 100x-1000x to ensure unique IDs on EVERY script run
ID_RANGES = {
    # Patient-specific resources (using 10M-100M ranges for maximum uniqueness)
    'Patient': (10000000, 10000000),  # Exactly 1 patient per generation
    'Encounter': (10100000, 19999999),  # Up to 10M encounters
    'Condition': (20000000, 39999999),  # Up to 20M conditions
    'Observation': (40000000, 99999999),  # Up to 60M observations (most common)
    'DiagnosticReport': (100000000, 119999999),  # Up to 20M diagnostic reports
    'MedicationRequest': (120000000, 139999999),  # Up to 20M medication requests
    'Procedure': (140000000, 159999999),  # Up to 20M procedures
    'DocumentReference': (160000000, 179999999),  # Up to 20M document references
    'Immunization': (180000000, 189999999),  # Up to 10M immunizations
    'CarePlan': (190000000, 199999999),  # Up to 10M care plans
    'Goal': (200000000, 209999999),  # Up to 10M goals
    'AllergyIntolerance': (210000000, 219999999),  # Up to 10M allergies
    'Binary': (220000000, 239999999),  # Up to 20M binary resources (images, documents)
    'Media': (240000000, 249999999),  # Up to 10M media resources
    'ImagingStudy': (250000000, 259999999),  # Up to 10M imaging studies
    'Claim': (260000000, 279999999),  # Up to 20M claims
    'ExplanationOfBenefit': (280000000, 299999999),  # Up to 20M EOBs
    'Provenance': (300000000, 319999999),  # Up to 20M provenance records
    'Composition': (320000000, 339999999),  # Up to 20M compositions
    'CareTeam': (340000000, 349999999),  # Up to 10M care teams
    'Medication': (350000000, 369999999),  # Up to 20M medications
    'MedicationAdministration': (370000000, 389999999),  # Up to 20M medication administrations
    'MedicationStatement': (390000000, 409999999),  # Up to 20M medication statements

    # Shared resources (across all patients, using 500M-900M ranges)
    'Practitioner': (500000000, 599999999),  # Up to 100M practitioners
    'PractitionerRole': (600000000, 699999999),  # Up to 100M practitioner roles
    'Organization': (700000000, 799999999),  # Up to 100M organizations
    'Location': (800000000, 899999999),  # Up to 100M locations
}

# ID Prefixes for each resource type (to make IDs alphanumeric per HAPI FHIR requirement)
# All prefixed with 't' to indicate test/synthetic data
ID_PREFIXES = {
    'Patient': 't',
    'Encounter': 't',
    'Condition': 't',
    'Observation': 't',
    'DiagnosticReport': 't',
    'MedicationRequest': 't',
    'Procedure': 't',
    'DocumentReference': 't',
    'Immunization': 't',
    'CarePlan': 't',
    'Goal': 't',
    'AllergyIntolerance': 't',
    'Binary': 't',
    'Media': 't',
    'ImagingStudy': 't',
    'Claim': 't',
    'ExplanationOfBenefit': 't',
    'Provenance': 't',
    'Composition': 't',
    'CareTeam': 't',
    'Medication': 't',
    'MedicationAdministration': 't',
    'MedicationStatement': 't',
    'Practitioner': 't',
    'PractitionerRole': 't',
    'Organization': 't',
    'Location': 't',
}

# athenaHealth ID prefixes by resource type
ATHENA_ID_PREFIXES = {
    'Patient': 'E',
    'Encounter': 'encounter',
    'Condition': 'Problem',
    'Observation': 'resultamb',
    'DiagnosticReport': 'clinicalresult',
    'MedicationRequest': 'medicationrequest',
    'Procedure': 'shb.7126',
    'DocumentReference': 'document',
    'Immunization': 'immunization',
    'CarePlan': 'careplan',
    'Goal': 'goal',
    'AllergyIntolerance': 'allergy',
    'Binary': 'binary',
    'Media': 'media',
    'ImagingStudy': 'imagingstudy',
    'Claim': 'claim',
    'ExplanationOfBenefit': 'eob',
    'Provenance': 'provenance',
    'Composition': 'composition',
    'CareTeam': 'careteam',
    'Medication': 'medication',
    'MedicationAdministration': 'medicationadministration',
    'MedicationStatement': 'medicationstatement',
    'PractitionerRole': 'practitionerrole',
}

# CVS Pharmacy locations for medication notes (rotate through these)
CVS_PHARMACIES = [
    {
        'name': 'CVS/Pharmacy #9245',
        'address': '12409 North Tatum Blvd, Phoenix, AZ 85032',
        'phone': '(602) 953-5290'
    },
    {
        'name': 'CVS/Pharmacy #10529',
        'address': '7111 East Bell Rd, Scottsdale, AZ 85254',
        'phone': '(480) 443-8014'
    },
    {
        'name': 'CVS/Pharmacy #9252',
        'address': '14672 N. Frank Lloyd Wright Blvd., Scottsdale, AZ 85260',
        'phone': '(480) 948-0255'
    }
]

# Virtual encounter dates (mark these as class: VR instead of AMB)
# Default is empty - no virtual encounters unless explicitly specified
VIRTUAL_ENCOUNTER_DATES = []


def build_uuid_mapping(bundle: Dict[str, Any], base_patient_id: int = 995000, generation_timestamp: int = None) -> Dict[str, Tuple[str, str]]:
    """
    Map all UUIDs to random numeric IDs within allocated ranges, seeded by patient ID + timestamp.
    Also builds an identifier-based mapping for conditional references.

    Adding timestamp to the seed ensures that regenerating the same patient produces DIFFERENT IDs
    each time, preventing ID conflicts in HAPI FHIR when uploading the same patient multiple times.

    Args:
        bundle: FHIR transaction bundle with UUID-based IDs
        base_patient_id: Patient ID used to seed randomization (default: 995000)
        generation_timestamp: Unix timestamp in milliseconds (default: current time)
                            Ensures unique IDs on each script run

    Returns:
        Dictionary mapping UUID -> (numeric_id, resource_type)
        Also maps identifier values -> (numeric_id, resource_type) for conditional refs
    """
    # Use current timestamp if not provided - ensures unique IDs every script run
    if generation_timestamp is None:
        generation_timestamp = int(datetime.now().timestamp() * 1000)  # milliseconds since epoch

    uuid_map = {}

    # Use high-precision timestamp with microseconds and process ID for maximum randomness
    # This ensures EVERY run generates completely different IDs, even if run in rapid succession
    import os
    import time
    timestamp_microseconds = int(time.time() * 1_000_000)  # microseconds since epoch
    process_id = os.getpid()
    random_salt = random.randint(0, 999999)

    # Create seed from multiple entropy sources for truly unique IDs every time
    seed_value = hash((base_patient_id, timestamp_microseconds, process_id, random_salt))
    rng = random.Random(seed_value)

    # Track used IDs per resource type to avoid collisions within this patient
    used_ids = {resource_type: set() for resource_type in ID_RANGES.keys()}

    # Track all used numeric IDs across ALL resource types to ensure global uniqueness
    all_used_ids = set()

    print("\nBuilding UUID to numeric ID mapping with HIGH ENTROPY...")
    print(f"  Timestamp (μs): {timestamp_microseconds}")
    print(f"  Process ID: {process_id}")
    print(f"  Random salt: {random_salt}")
    print(f"  This ensures UNIQUE IDs every single run, preventing 409 conflicts")

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')
        resource_id = resource.get('id')

        if not resource_type or not resource_id:
            continue

        # Skip if already a numeric string
        if resource_id.isdigit():
            continue

        # Allocate random numeric ID from appropriate range
        if resource_type in ID_RANGES:
            start_range, end_range = ID_RANGES[resource_type]

            # For Patient resource, use the provided patient ID directly
            if resource_type == 'Patient':
                numeric_part = base_patient_id
                used_ids[resource_type].add(numeric_part)
                all_used_ids.add(numeric_part)
            else:
                # Generate truly unique random ID with high entropy for EVERY run
                # Combine multiple entropy sources: timestamp microseconds, process ID, random salt, original UUID
                # This ensures IDs are DIFFERENT every single time, even for rapid successive runs
                resource_seed = hash((
                    resource_type,
                    base_patient_id,
                    timestamp_microseconds,  # High-precision timestamp
                    process_id,              # Process-specific
                    random_salt,             # Random per-run
                    resource_id,             # Original UUID
                    rng.random()             # Additional randomness
                ))
                resource_rng = random.Random(resource_seed)

                # Generate random offset within the resource type's designated range
                random_offset = resource_rng.randint(0, end_range - start_range)
                candidate_id = start_range + random_offset

                # If there's a collision, try incrementing within range until we find a free ID
                max_attempts = end_range - start_range + 1
                numeric_part = None

                for attempt in range(max_attempts):
                    test_id = start_range + ((random_offset + attempt) % (end_range - start_range + 1))

                    # Check if ID already used globally (across all resource types)
                    if test_id not in all_used_ids:
                        numeric_part = test_id
                        used_ids[resource_type].add(numeric_part)
                        all_used_ids.add(numeric_part)
                        break

                if numeric_part is None:
                    # This should never happen unless the entire range is exhausted
                    print(f"  ERROR: Could not find unique ID for {resource_type}, range exhausted!")
                    raise ValueError(f"ID range exhausted for {resource_type}")

            # Add prefix to make ID alphanumeric (HAPI FHIR requirement)
            prefix = ID_PREFIXES.get(resource_type, 'x')
            alphanumeric_id = f"{prefix}{numeric_part}"

            uuid_map[resource_id] = (alphanumeric_id, resource_type)
            print(f"  {resource_type}/{resource_id} -> {alphanumeric_id}")

            # Also map identifiers for conditional references
            # For Practitioner: use NPI value
            # For Organization/Location: use synthetichealth identifier value
            # IMPORTANT: Skip if identifier value is already a UUID of another resource
            # (e.g., EOB identifier pointing to Claim UUID - they should have different IDs!)
            identifiers = resource.get('identifier', [])
            for identifier in identifiers:
                system = identifier.get('system', '')
                value = identifier.get('value', '')

                if value and value not in uuid_map:
                    # Only map if this value isn't already mapped to another resource
                    uuid_map[value] = (alphanumeric_id, resource_type)
                    print(f"    Identifier {value} -> {alphanumeric_id}")

        else:
            print(f"  WARNING: No ID range defined for {resource_type}, skipping {resource_id}")

    print(f"\nMapped {len(uuid_map)} UUIDs and identifiers to alphanumeric IDs")
    return uuid_map


def convert_all_ids(bundle: Dict[str, Any], uuid_map: Dict[str, Tuple[str, str]]) -> None:
    """
    Replace all resource IDs with numeric strings.

    Args:
        bundle: FHIR transaction bundle
        uuid_map: UUID to numeric ID mapping
    """
    print("\nConverting resource IDs to numeric strings...")

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        resource_id = resource.get('id')
        resource_type = resource.get('resourceType')

        if resource_id and resource_id in uuid_map:
            numeric_id, _ = uuid_map[resource_id]
            resource['id'] = numeric_id

            # Change POST to PUT with ID in URL so HAPI FHIR uses our specified ID
            # instead of generating its own
            request = entry.get('request', {})
            if request.get('method') == 'POST':
                request['method'] = 'PUT'
                request['url'] = f"{resource_type}/{numeric_id}"
                print(f"  Updated {resource_type}/{resource_id} -> PUT {resource_type}/{numeric_id}")

            # Remove fullUrl if present (not required for HAPI FHIR uploads)
            if 'fullUrl' in entry:
                del entry['fullUrl']


def add_athena_extensions(resource: Dict[str, Any], resource_type: str, resource_id: str, practice_id: str,
                          practice_org_id: str = None, chart_sharing_org_id: str = None) -> None:
    """
    Add athenaHealth-specific extensions to resource.

    Extensions added:
    - practice: Practice Organization reference (valueReference)
    - chart-sharing-group: Chart sharing group Organization reference (valueReference)
    - athenaId: AthenaHealth resource identifier (valueString)

    Args:
        resource: FHIR resource
        resource_type: Type of resource (Patient, Encounter, etc.)
        resource_id: Numeric resource ID
        practice_id: Practice identifier (e.g., "a-16349")
        practice_org_id: Practice Organization ID (default: first org in bundle)
        chart_sharing_org_id: Chart sharing Organization ID (default: second org or same as practice)
    """
    if 'extension' not in resource:
        resource['extension'] = []

    # Practice extension - use valueReference to first Organization
    practice_ext = {
        "url": "https://fhir.athena.io/StructureDefinition/ah-practice",
        "valueReference": {
            "reference": f"Organization/{practice_org_id}" if practice_org_id else "Organization/8000000"
        }
    }

    # Chart sharing group extension - use valueReference to chart-sharing Organization
    chart_sharing_ext = {
        "url": "https://fhir.athena.io/StructureDefinition/ah-chart-sharing-group",
        "valueReference": {
            "reference": f"Organization/{chart_sharing_org_id}" if chart_sharing_org_id else "Organization/8000000"
        }
    }

    # athenaId extension - keep as valueString
    athena_prefix = ATHENA_ID_PREFIXES.get(resource_type, 'unknown')
    athena_id = f"{practice_id}.{athena_prefix}-{resource_id}"
    athena_id_ext = {
        "url": "athenaId",
        "valueString": athena_id
    }

    # Add extensions (avoid duplicates)
    existing_urls = {ext.get('url') for ext in resource['extension']}

    if practice_ext['url'] not in existing_urls:
        resource['extension'].append(practice_ext)
    if chart_sharing_ext['url'] not in existing_urls:
        resource['extension'].append(chart_sharing_ext)
    if athena_id_ext['url'] not in existing_urls:
        resource['extension'].append(athena_id_ext)


def add_metadata(resource: Dict[str, Any]) -> None:
    """
    Add FHIR metadata (source, security tags).

    Note: versionId and lastUpdated are server-managed fields and should NOT be included
    when creating resources with client-assigned IDs using PUT requests.

    Args:
        resource: FHIR resource
    """
    if 'meta' not in resource:
        resource['meta'] = {}

    meta = resource['meta']

    # Do NOT add versionId or lastUpdated - these are server-managed fields
    # that cause "client-assigned ID constraint failure" errors when using PUT requests

    # source
    if 'source' not in meta:
        meta['source'] = 'https://www.thetarho.com/fhir'

    # security tags
    if 'security' not in meta:
        meta['security'] = [
            {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
                "code": "HTEST",
                "display": "test health data"
            }
        ]


def add_identifiers(resource: Dict[str, Any], resource_type: str, resource_id: str, practice_id: str) -> None:
    """
    Add system and value identifiers to resource.
    Removes all UUID-based identifiers and restructures identifier order.

    Args:
        resource: FHIR resource
        resource_type: Type of resource
        resource_id: Numeric resource ID
        practice_id: Practice identifier
    """
    # UUID pattern to detect UUID identifiers
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

    if 'identifier' not in resource:
        resource['identifier'] = []

    # Filter out UUID-based identifiers from existing identifiers
    # Remove identifiers from Synthea and any UUID values
    non_uuid_identifiers = []
    for id_obj in resource['identifier']:
        system = id_obj.get('system', '')
        value = id_obj.get('value', '')

        # Skip Synthea identifiers
        if 'synthea' in system.lower():
            continue

        # Skip hospital.smarthealthit.org identifiers (also UUIDs)
        if 'smarthealthit' in system.lower():
            continue

        # Skip ThetaRho identifiers (we'll add them in correct order)
        if 'thetarho.com' in system.lower():
            continue

        # Skip any identifier with UUID value
        if uuid_pattern.match(value):
            continue

        # Keep non-UUID identifiers (SSN, DL, Passport, etc.)
        non_uuid_identifiers.append(id_obj)

    # Build new identifier list in correct order:
    # 1. Athena ID (a-11783.E-t8080)
    # 2. Patient ID (t8080) - for Patient resources only
    # 3. All other non-UUID identifiers (SSN, DL, Passport, etc.)

    new_identifiers = []

    # Add athena identifier first (full format: a-16349.E-t1000000)
    athena_prefix = ATHENA_ID_PREFIXES.get(resource_type, 'unknown')
    athena_id = f"{practice_id}.{athena_prefix}-{resource_id}"

    athena_identifier = {
        "system": "https://www.thetarho.com/fhir/identifiers/athena",
        "value": athena_id
    }
    new_identifiers.append(athena_identifier)

    # For Patient resources, add simple patient ID identifier second (t1000000)
    # This allows indexing with just the patient ID
    if resource_type == 'Patient':
        simple_patient_identifier = {
            "system": "https://www.thetarho.com/fhir/identifiers/patient",
            "value": resource_id
        }
        new_identifiers.append(simple_patient_identifier)

    # Add all other non-UUID identifiers (SSN, DL, Passport, etc.)
    new_identifiers.extend(non_uuid_identifiers)

    # Replace identifier array with restructured list
    resource['identifier'] = new_identifiers


def update_all_references(bundle: Dict[str, Any], uuid_map: Dict[str, Tuple[str, str]]) -> None:
    """
    Update all resource references (resource.reference fields) to use numeric IDs.

    Args:
        bundle: FHIR transaction bundle
        uuid_map: UUID to numeric ID mapping
    """
    print("\nUpdating resource references...")
    reference_count = 0
    conditional_ref_count = 0

    def update_reference(obj: Any) -> None:
        nonlocal reference_count, conditional_ref_count

        if isinstance(obj, dict):
            # Check if this is a reference object
            if 'reference' in obj:
                ref = obj['reference']

                # Handle three formats:
                # 1. "urn:uuid:abc-def-123" -> "ResourceType/numeric_id"
                # 2. "ResourceType/abc-def-123" -> "ResourceType/numeric_id"
                # 3. "ResourceType?identifier=..." -> "ResourceType/numeric_id"

                # Check for conditional reference (e.g., "Practitioner?identifier=...")
                conditional_match = re.match(r'([A-Za-z]+)\?identifier=', ref)
                if conditional_match:
                    resource_type = conditional_match.group(1)
                    # Extract the identifier value to use as UUID key
                    identifier_match = re.search(r'identifier=([^|]+)\|(.+)', ref)
                    if identifier_match:
                        # Use the UUID/identifier part as the lookup key
                        identifier_value = identifier_match.group(2)
                        if identifier_value in uuid_map:
                            numeric_id, _ = uuid_map[identifier_value]
                            obj['reference'] = f"{resource_type}/{numeric_id}"
                            conditional_ref_count += 1
                            reference_count += 1
                    return

                # First try to extract UUID from "urn:uuid:UUID" format
                urn_match = re.match(r'urn:uuid:([\w-]+)', ref)
                if urn_match:
                    uuid = urn_match.group(1)
                    if uuid in uuid_map:
                        numeric_id, resource_type_from_map = uuid_map[uuid]
                        obj['reference'] = f"{resource_type_from_map}/{numeric_id}"
                        reference_count += 1
                else:
                    # Try "ResourceType/UUID" format
                    type_match = re.match(r'([A-Za-z]+)/([\w-]+)', ref)
                    if type_match:
                        resource_type, uuid = type_match.groups()
                        if uuid in uuid_map:
                            numeric_id, _ = uuid_map[uuid]
                            obj['reference'] = f"{resource_type}/{numeric_id}"
                            reference_count += 1

            # Recursively process all values
            for value in obj.values():
                update_reference(value)

        elif isinstance(obj, list):
            for item in obj:
                update_reference(item)

    for entry in bundle.get('entry', []):
        update_reference(entry.get('resource', {}))

    print(f"Updated {reference_count} references ({conditional_ref_count} conditional references converted)")


def mark_virtual_encounters(bundle: Dict[str, Any], virtual_dates: List[str]) -> None:
    """
    Mark encounters on specified dates as virtual (class: VR instead of AMB).

    Args:
        bundle: FHIR transaction bundle
        virtual_dates: List of dates (YYYY-MM-DD format) for virtual encounters
    """
    print(f"\nMarking virtual encounters for dates: {virtual_dates}")
    virtual_count = 0

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})

        if resource.get('resourceType') == 'Encounter':
            period = resource.get('period', {})
            start_date = period.get('start', '')[:10]  # Get YYYY-MM-DD part

            if start_date in virtual_dates:
                # Update class to virtual
                if 'class' in resource:
                    resource['class'] = {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                        "code": "VR",
                        "display": "virtual"
                    }
                    virtual_count += 1
                    print(f"  Marked Encounter/{resource.get('id')} on {start_date} as virtual")

    print(f"Marked {virtual_count} encounters as virtual")


def add_pharmacy_notes(bundle: Dict[str, Any]) -> None:
    """
    Add CVS pharmacy details to MedicationRequest notes (rotate through pharmacies).

    Args:
        bundle: FHIR transaction bundle
    """
    print("\nAdding pharmacy notes to MedicationRequests...")
    pharmacy_index = 0
    med_count = 0

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})

        if resource.get('resourceType') == 'MedicationRequest':
            pharmacy = CVS_PHARMACIES[pharmacy_index % len(CVS_PHARMACIES)]

            pharmacy_note = {
                "text": f"Pharmacy: {pharmacy['name']}, {pharmacy['address']}, Phone: {pharmacy['phone']}"
            }

            if 'note' not in resource:
                resource['note'] = []

            resource['note'].append(pharmacy_note)
            med_count += 1
            pharmacy_index += 1

    print(f"Added pharmacy notes to {med_count} MedicationRequests")


def fix_codeable_concept_text_fields(bundle: Dict[str, Any]) -> None:
    """
    Add text fields to CodeableConcept elements in multiple resource types.

    FhirDataValidationQueryService expects text fields in CodeableConcepts for:
    - AllergyIntolerance: clinicalStatus.text, verificationStatus.text, code.text
    - Condition: clinicalStatus.text, verificationStatus.text, code.text
    - Immunization: vaccineCode.text
    - MedicationRequest: medicationCodeableConcept/medicationReference display
    - Observation: code.text (with display from coding)
    - DiagnosticReport: code.text

    This function ensures these text fields are present to prevent NullPointerException
    in ThetaRho services.

    Args:
        bundle: FHIR bundle containing resources
    """
    allergy_count = 0
    condition_count = 0
    immunization_count = 0
    observation_count = 0
    diagnostic_report_count = 0

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')

        # Fix AllergyIntolerance and Condition resources
        if resource_type in ['AllergyIntolerance', 'Condition']:
            # Fix clinicalStatus text field
            if 'clinicalStatus' in resource:
                clinical_status = resource['clinicalStatus']

                # Add text field based on coding
                if 'coding' in clinical_status and clinical_status['coding']:
                    code = clinical_status['coding'][0].get('code', '')

                    # Map common clinical status codes to text
                    status_text_map = {
                        'active': 'Active',
                        'inactive': 'Inactive',
                        'resolved': 'Resolved',
                        'recurrence': 'Recurrence',
                        'relapse': 'Relapse',
                        'remission': 'Remission'
                    }

                    if code in status_text_map:
                        clinical_status['text'] = status_text_map[code]

            # Fix verificationStatus text field
            if 'verificationStatus' in resource:
                verification_status = resource['verificationStatus']

                # Add text field based on coding
                if 'coding' in verification_status and verification_status['coding']:
                    code = verification_status['coding'][0].get('code', '')

                    # Map common verification status codes to text
                    status_text_map = {
                        'confirmed': 'Confirmed',
                        'unconfirmed': 'Unconfirmed',
                        'provisional': 'Provisional',
                        'differential': 'Differential',
                        'refuted': 'Refuted',
                        'entered-in-error': 'Entered in Error'
                    }

                    if code in status_text_map:
                        verification_status['text'] = status_text_map[code]

            # Ensure code.text is populated from display if not present
            if 'code' in resource and 'text' not in resource['code']:
                code_cc = resource['code']
                if 'coding' in code_cc and code_cc['coding']:
                    display = code_cc['coding'][0].get('display', '')
                    if display:
                        code_cc['text'] = display

            if resource_type == 'AllergyIntolerance':
                allergy_count += 1
            else:
                condition_count += 1

        # Fix Immunization resources
        elif resource_type == 'Immunization':
            # Ensure vaccineCode.text is populated
            if 'vaccineCode' in resource and 'text' not in resource['vaccineCode']:
                vaccine_code = resource['vaccineCode']
                if 'coding' in vaccine_code and vaccine_code['coding']:
                    display = vaccine_code['coding'][0].get('display', '')
                    if display:
                        vaccine_code['text'] = display

            immunization_count += 1

        # Fix Observation resources
        elif resource_type == 'Observation':
            # Ensure code.text is populated
            if 'code' in resource and 'text' not in resource['code']:
                obs_code = resource['code']
                if 'coding' in obs_code and obs_code['coding']:
                    # Use the first coding display
                    display = obs_code['coding'][0].get('display', '')
                    if display:
                        obs_code['text'] = display

            observation_count += 1

        # Fix DiagnosticReport resources
        elif resource_type == 'DiagnosticReport':
            # Ensure code.text is populated
            if 'code' in resource and 'text' not in resource['code']:
                dr_code = resource['code']
                if 'coding' in dr_code and dr_code['coding']:
                    display = dr_code['coding'][0].get('display', '')
                    if display:
                        dr_code['text'] = display

            diagnostic_report_count += 1

    print(f"Fixed text fields in:")
    print(f"  - {allergy_count} AllergyIntolerance resources")
    print(f"  - {condition_count} Condition resources")
    print(f"  - {immunization_count} Immunization resources")
    print(f"  - {observation_count} Observation resources")
    print(f"  - {diagnostic_report_count} DiagnosticReport resources")


def add_category_text_to_conditions(bundle: Dict[str, Any]) -> None:
    """
    Add text field to Condition.category CodeableConcept for backend compatibility.

    Backend (FhirQueryService.java:3333) expects category to have a text field:
        codeableConceptCategory.getText()

    Synthea generates category with only coding array, no text field.
    This function adds the text field from coding[0].display.

    Args:
        bundle: FHIR bundle containing Condition resources
    """
    fixed_count = 0

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})

        if resource.get('resourceType') != 'Condition':
            continue

        category_list = resource.get('category', [])
        for category_cc in category_list:
            # Check if text field already exists
            if 'text' in category_cc:
                continue

            # Get text from coding[0].display
            coding_list = category_cc.get('coding', [])
            if coding_list:
                display = coding_list[0].get('display', '')
                if display:
                    category_cc['text'] = display
                    fixed_count += 1

    if fixed_count > 0:
        print(f"Added text field to {fixed_count} Condition category CodeableConcepts")


def add_diagnostic_report_subtypes(bundle: Dict[str, Any]) -> None:
    """
    Add dr_subtype tags to DiagnosticReport resources based on LOINC codes.

    FhirDataValidationQueryService groups DiagnosticReports by dr_subtype tag.
    This function maps common LOINC codes to their corresponding subtypes.

    Subtype categories:
    - drBMP: Basic Metabolic Panel
    - drCBC: Complete Blood Count
    - drCK: Creatine Kinase
    - drCMP: Comprehensive Metabolic Panel
    - drCRP: C-Reactive Protein
    - drDHEA: DHEA tests
    - drHBA1C: Hemoglobin A1c
    - drLP: Lipid Panel
    - drPTINR: PT/INR
    - drSTI: STI tests
    - drTSH: Thyroid Stimulating Hormone
    - drUA: Urinalysis
    - drIMG: Imaging (generated separately for ImagingStudy resources)
    - drOTHER: Other/Unknown

    Args:
        bundle: FHIR bundle containing DiagnosticReport resources
    """
    # LOINC code to dr_subtype mapping
    loinc_subtype_map = {
        # Basic Metabolic Panel
        '24320-4': 'drBMP', '24321-2': 'drBMP', '51990-0': 'drBMP', '70219-1': 'drBMP', '89044-2': 'drBMP',

        # Complete Blood Count
        '58410-2': 'drCBC', '57021-8': 'drCBC', '57782-5': 'drCBC', '69742-5': 'drCBC',

        # Comprehensive Metabolic Panel
        '24322-0': 'drCMP', '24323-8': 'drCMP',

        # Hemoglobin A1c
        '4548-4': 'drHBA1C',

        # Lipid Panel
        '57698-3': 'drLP', '24331-1': 'drLP',

        # STI Panel
        '24111-7': 'drSTI',

        # Thyroid Stimulating Hormone
        '3016-3': 'drTSH',

        # Urinalysis
        '24356-8': 'drUA', '24357-6': 'drUA'
    }

    # Keyword-based subtype detection for codes not in the map
    def detect_subtype_from_text(text: str) -> str:
        """Detect dr_subtype from text using keyword matching."""
        if not text:
            return 'drOTHER'

        text_lower = text.lower()

        if 'bmp' in text_lower or 'basic metabol' in text_lower:
            return 'drBMP'
        elif 'cbc' in text_lower or 'complete blood count' in text_lower or 'hemogram' in text_lower:
            return 'drCBC'
        elif 'cmp' in text_lower or 'comprehensive metabol' in text_lower:
            return 'drCMP'
        elif 'hba1c' in text_lower or 'hemoglobin a1c' in text_lower:
            return 'drHBA1C'
        elif 'lipid panel' in text_lower or 'cholesterol' in text_lower:
            return 'drLP'
        elif 'urinalysis' in text_lower or 'urine' in text_lower:
            return 'drUA'
        elif 'tsh' in text_lower or 'thyroid stimulating' in text_lower:
            return 'drTSH'
        else:
            return 'drOTHER'

    tagged_count = 0

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})

        if resource.get('resourceType') != 'DiagnosticReport':
            continue

        # Try to determine subtype from LOINC code
        subtype = 'drOTHER'
        code_cc = resource.get('code', {})

        if 'coding' in code_cc:
            for coding in code_cc['coding']:
                if coding.get('system') == 'http://loinc.org':
                    loinc_code = coding.get('code', '')
                    if loinc_code in loinc_subtype_map:
                        subtype = loinc_subtype_map[loinc_code]
                        break
                    else:
                        # Try keyword detection from display
                        display = coding.get('display', '')
                        subtype = detect_subtype_from_text(display)
                        break

        # Fallback: detect from text field
        if subtype == 'drOTHER' and 'text' in code_cc:
            subtype = detect_subtype_from_text(code_cc['text'])

        # Add dr_subtype tag to meta
        if 'meta' not in resource:
            resource['meta'] = {}

        if 'tag' not in resource['meta']:
            resource['meta']['tag'] = []

        # Check if dr_subtype tag already exists
        existing_tag = None
        for tag in resource['meta']['tag']:
            if tag.get('system') == 'http://thetarho.ai/fhir/CodeSystem/dr_subtype':
                existing_tag = tag
                break

        if existing_tag:
            # Update existing tag
            existing_tag['code'] = f"dr_subtype:{subtype}"
            existing_tag['display'] = subtype
        else:
            # Add new tag
            resource['meta']['tag'].append({
                'system': 'http://thetarho.ai/fhir/CodeSystem/dr_subtype',
                'code': f"dr_subtype:{subtype}",
                'display': subtype
            })

        # Add image_type tag for imaging DiagnosticReports (required for OpenSearch indexing)
        if subtype == 'drIMG':
            # Check if image_type tag already exists
            has_image_type_tag = any(
                tag.get('system') == 'http://thetarho.ai/fhir/CodeSystem/image_type'
                for tag in resource['meta']['tag']
            )

            if not has_image_type_tag:
                resource['meta']['tag'].append({
                    'system': 'http://thetarho.ai/fhir/CodeSystem/image_type',
                    'code': 'image_type:IMG',
                    'display': 'IMG'
                })

        tagged_count += 1

    print(f"Added dr_subtype tags to {tagged_count} DiagnosticReport resources")


def remove_clinical_documentation_diagnostic_reports(bundle: Dict[str, Any]) -> None:
    """
    Remove DiagnosticReport resources that represent clinical documentation rather than lab/diagnostic tests.
    Also removes Provenance resources since they are not used by ThetaRho app suite.

    Clinical documentation (H&P notes, consult notes, etc.) should only exist as Composition resources,
    not as DiagnosticReports. This function removes DiagnosticReports with clinical documentation LOINC codes
    to prevent them from appearing in the diagnostic results section of the UI.

    Clinical Documentation LOINC Codes to Remove:
    - 34117-2: History and physical note
    - 11488-4: Consult note
    - 18842-5: Discharge summary
    - 11506-3: Progress note
    - 28570-0: Procedure note
    - 34133-9: Summarization of episode note
    - 11504-8: Surgical operation note

    Args:
        bundle: FHIR bundle potentially containing clinical documentation DiagnosticReports
    """
    # LOINC codes representing clinical documentation (not lab/diagnostic tests)
    clinical_doc_loinc_codes = {
        '34117-2',  # History and physical note
        '11488-4',  # Consult note
        '18842-5',  # Discharge summary
        '11506-3',  # Progress note
        '28570-0',  # Procedure note
        '34133-9',  # Summarization of episode note
        '11504-8',  # Surgical operation note
    }

    removed_dr_count = 0
    removed_prov_count = 0
    original_dr_count = 0
    original_prov_count = 0
    entries_to_keep = []

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')

        # Remove Provenance resources (not used by ThetaRho app suite)
        if resource_type == 'Provenance':
            original_prov_count += 1
            removed_prov_count += 1
            continue

        # Check DiagnosticReport resources for clinical documentation
        if resource_type == 'DiagnosticReport':
            original_dr_count += 1

            # Check if this DiagnosticReport has a clinical documentation LOINC code
            is_clinical_doc = False
            code_cc = resource.get('code', {})

            if 'coding' in code_cc:
                for coding in code_cc['coding']:
                    if coding.get('system') == 'http://loinc.org':
                        loinc_code = coding.get('code', '')
                        if loinc_code in clinical_doc_loinc_codes:
                            is_clinical_doc = True
                            removed_dr_count += 1
                            print(f"  Removing DiagnosticReport/{resource.get('id')}: {coding.get('display')} (LOINC {loinc_code})")
                            break

            # Only keep if NOT clinical documentation
            if not is_clinical_doc:
                entries_to_keep.append(entry)
        else:
            # Keep all other resource types
            entries_to_keep.append(entry)

    # Update bundle with filtered entries
    bundle['entry'] = entries_to_keep

    print(f"\nRemoved {removed_dr_count} of {original_dr_count} DiagnosticReport resources (clinical documentation)")
    print(f"Remaining DiagnosticReport resources: {original_dr_count - removed_dr_count} (lab/diagnostic tests only)")
    print(f"Removed {removed_prov_count} Provenance resources (not used by app suite)")


def get_dr_subtype_from_modality(modality_code: str, procedure_text: str = "") -> str:
    """
    Map imaging modality to DiagnosticReport subtype tag.

    Returns specific imaging subtype (drCT, drUS, drNMR) when possible,
    falls back to drRAD for general radiology.

    Args:
        modality_code: DICOM modality code or display text
        procedure_text: Optional procedure description for additional context

    Returns:
        DR subtype code (drCT, drUS, drNMR, or drRAD)
    """
    modality_lower = modality_code.lower()
    procedure_lower = procedure_text.lower()

    # Map specific modalities to subtypes
    if 'ct' in modality_lower or 'computed tomography' in procedure_lower:
        return 'drCT'
    elif 'us' in modality_lower or 'ultrasound' in modality_lower or 'ultrasonography' in procedure_lower:
        return 'drUS'
    elif 'mr' in modality_lower or 'nmr' in modality_lower or 'magnetic resonance' in procedure_lower:
        return 'drNMR'
    else:
        # Default to general radiology for X-ray, echo, fundus photography, etc.
        return 'drRAD'


def generate_diagnostic_reports_for_imaging_studies(bundle: Dict[str, Any],
                                                      practice_id: str = "a-16349",
                                                      practice_org_id: str = None,
                                                      chart_sharing_org_id: str = None) -> None:
    """
    Generate DiagnosticReport resources for ImagingStudy resources with dual subtype tags.

    Real-world clinical workflow:
    1. Imaging procedure is performed → ImagingStudy created
    2. Images are captured → Binary resources created
    3. Radiologist interprets images → DiagnosticReport created
    4. DiagnosticReport references ImagingStudy via imagingStudy[] field

    This function simulates step 3 by creating DiagnosticReport resources tagged with:
    - drIMG: Generic imaging marker (functional)
    - drRAD/drCT/drUS/drNMR: Specific modality type (semantic)

    This dual-tagging enables both:
    - Generic "all images" queries (via drIMG)
    - Specific modality queries like "latest radiology" (via drRAD, drCT, etc.)

    Backend Requirement (FhirQueryService.java:1053-1172):
    - getImaging() searches for DiagnosticReport resources
    - Expects meta.tag with dr_subtype:drIMG and specific modality subtype
    - Returns results via imagingStudy references

    Args:
        bundle: FHIR bundle containing ImagingStudy resources
        practice_id: Practice ID for athena identifiers (e.g., "a-11783")
        practice_org_id: Practice organization resource ID
        chart_sharing_org_id: Chart sharing group organization ID
    """
    print("\nGenerating DiagnosticReport resources for ImagingStudy resources...")

    # Find all ImagingStudy resources
    imaging_studies = []
    patient_ref = None

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') == 'ImagingStudy':
            imaging_studies.append(resource)
            if not patient_ref and 'subject' in resource:
                patient_ref = resource['subject'].get('reference')

    if not imaging_studies:
        print("  No ImagingStudy resources found - skipping DiagnosticReport generation")
        return

    if not practice_org_id and patient_ref:
        # Try to extract practice org from patient reference or use default
        practice_org_id = chart_sharing_org_id if chart_sharing_org_id else "t774367587"

    # Generate DiagnosticReport IDs from the DiagnosticReport range
    # Use offset to avoid collisions with existing DiagnosticReports
    dr_id_start = ID_RANGES['DiagnosticReport'][0] + 50000
    generated_count = 0

    for idx, imaging_study in enumerate(imaging_studies):
        # Extract key information from ImagingStudy
        imaging_id = imaging_study.get('id')
        subject_ref = imaging_study.get('subject', {}).get('reference', patient_ref)
        encounter_ref = imaging_study.get('encounter', {}).get('reference')
        study_date = imaging_study.get('started')
        procedure_codes = imaging_study.get('procedureCode', [])
        location_ref = imaging_study.get('location', {})
        modality = "Unknown"

        # Extract modality from first series
        series_list = imaging_study.get('series', [])
        if series_list:
            modality_coding = series_list[0].get('modality', {})
            modality = modality_coding.get('display', modality_coding.get('code', 'Unknown'))

        # Generate unique DiagnosticReport ID
        dr_id_numeric = dr_id_start + idx
        dr_id = f"{ID_PREFIXES['DiagnosticReport']}{dr_id_numeric}"
        athena_id = f"{practice_id}.clinicalresult-{dr_id}"

        # Create procedure code for DiagnosticReport
        if procedure_codes:
            # Use the imaging study's procedure code
            code = procedure_codes[0]
        else:
            # Default imaging code
            code = {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "18748-4",
                    "display": "Diagnostic imaging study"
                }],
                "text": "Diagnostic imaging study"
            }

        # Generate conclusion based on modality and procedure
        procedure_text = code.get('text', 'Imaging study')
        conclusion = f"{procedure_text} completed. {modality} imaging performed. See referenced ImagingStudy/{imaging_id} for detailed image data."

        # Determine specific DR subtype based on modality
        specific_subtype = get_dr_subtype_from_modality(modality, procedure_text)

        # Generate placeholder image URLs using Picsum for this imaging study
        image_urls = []
        try:
            # Generate one image URL per instance in the imaging study
            # Use Picsum (Lorem Picsum) for random placeholder images
            for series in series_list:
                for instance_idx, instance in enumerate(series.get('instance', [])):
                    # Generate a unique seed based on the DiagnosticReport ID and instance index
                    # This ensures the same image is generated for the same DR each time
                    seed = hash(f"{dr_id}_{instance_idx}") % 1000

                    # Create Picsum URL: https://picsum.photos/seed/{seed}/512/512
                    # This returns a random 512x512 image with consistent seed
                    picsum_url = f"https://picsum.photos/seed/{seed}/512/512"
                    image_urls.append(picsum_url)

        except Exception as e:
            print(f"  ⚠️  Error generating image URLs for DiagnosticReport {dr_id}: {e}")

        # Create DiagnosticReport resource with dual tagging
        diagnostic_report = {
            "resourceType": "DiagnosticReport",
            "id": dr_id,
            "meta": {
                "profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-diagnosticreport-note"],
                "source": "https://www.thetarho.com/fhir",
                "security": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
                    "code": "HTEST",
                    "display": "test health data"
                }],
                "tag": [
                    {
                        "system": "http://thetarho.ai/fhir/CodeSystem/dr_subtype",
                        "code": f"dr_subtype:{specific_subtype}",
                        "display": specific_subtype
                    },
                    {
                        "system": "http://thetarho.ai/fhir/CodeSystem/dr_subtype",
                        "code": "dr_subtype:drIMG",
                        "display": "drIMG"
                    },
                    {
                        "system": "http://thetarho.ai/fhir/CodeSystem/image_type",
                        "code": "image_type:IMG",
                        "display": "IMG"
                    }
                ]
            },
            "identifier": [{
                "system": "https://www.thetarho.com/fhir/identifiers/athena",
                "value": athena_id
            }],
            "status": "final",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                    "code": "IMG",
                    "display": "Diagnostic Imaging"
                }]
            }],
            "code": code,
            "subject": {"reference": subject_ref},
            "effectiveDateTime": study_date,
            "issued": study_date,
            "conclusion": conclusion,
            "text": {
                "status": "generated",
                "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">\nEXAM DESCRIPTION: {procedure_text}\n{modality} imaging study performed on {study_date[:10] if study_date else 'unknown date'}. {conclusion}\n</div>"
            },
            "imagingStudy": [{
                "reference": f"ImagingStudy/{imaging_id}",
                "display": procedure_text
            }],
            "extension": []
        }

        # Add encounter if available
        if encounter_ref:
            diagnostic_report['encounter'] = {"reference": encounter_ref}

        # Add extensions for athena compatibility
        if practice_org_id:
            diagnostic_report['extension'].append({
                "url": "https://fhir.athena.io/StructureDefinition/ah-practice",
                "valueReference": {"reference": f"Organization/{practice_org_id}"}
            })
            diagnostic_report['extension'].append({
                "url": "https://fhir.athena.io/StructureDefinition/ah-chart-sharing-group",
                "valueReference": {"reference": f"Organization/{practice_org_id}"}
            })

        diagnostic_report['extension'].append({
            "url": "athenaId",
            "valueString": athena_id
        })

        # Add imageUrls extension with Picsum URLs (semicolon-separated)
        if image_urls:
            diagnostic_report['extension'].append({
                "url": "imageUrls",
                "valueString": ';'.join(image_urls)
            })
            print(f"  ✓ {dr_id}: Generated {len(image_urls)} Picsum image URL(s)")

        # Add to bundle
        bundle['entry'].append({
            "resource": diagnostic_report,
            "request": {
                "method": "PUT",
                "url": f"DiagnosticReport/{dr_id}"
            }
        })

        generated_count += 1

    print(f"Generated {generated_count} DiagnosticReport resources with dual tags (drIMG + modality-specific) for {len(imaging_studies)} ImagingStudy resources")


def convert_medication_codeable_concept_to_reference(bundle: Dict[str, Any], practice_id: str = "a-16349",
                                                      practice_org_id: str = None) -> None:
    """
    Convert MedicationRequest.medicationCodeableConcept to medicationReference with display.

    FhirQueryService.java:3383 expects MedicationRequest.medication to be a Reference type
    with a display field containing the medication name. Synthea generates inline
    medicationCodeableConcept which causes ClassCastException, and also generates
    medicationReference without display field.

    This function:
    1. Detects MedicationRequest resources with medicationCodeableConcept
    2. Creates a proper Medication resource with the same structure as Synthea-generated ones
    3. Creates medicationReference pointing to the new Medication resource
    4. Removes medicationCodeableConcept
    5. For existing medicationReference without display, looks up Medication resource and adds display

    Args:
        bundle: FHIR bundle containing MedicationRequest resources
        practice_id: Practice identifier for athenaHealth extensions
        practice_org_id: Practice Organization ID for extensions
    """
    # Build map of Medication ID -> (name, code) for reference lookup
    med_map = {}
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') == 'Medication':
            med_id = resource.get('id')
            code = resource.get('code', {})
            name = code.get('text', '')
            if not name and code.get('coding'):
                name = code['coding'][0].get('display', '')
            if med_id:
                med_map[med_id] = {'name': name, 'code': code}

    # Get first Organization ID if not provided
    if not practice_org_id:
        for entry in bundle.get('entry', []):
            resource = entry.get('resource', {})
            if resource.get('resourceType') == 'Organization':
                practice_org_id = resource.get('id')
                break

    converted_count = 0
    display_added_count = 0
    medications_created = 0
    new_medication_entries = []

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})

        if resource.get('resourceType') != 'MedicationRequest':
            continue

        # Case 1: Already has medicationReference - ensure it has display and valid reference
        if 'medicationReference' in resource:
            med_ref = resource['medicationReference']
            ref = med_ref.get('reference', '')

            # Extract Medication ID from reference
            # Handle both "Medication/123" and "urn:uuid:xxx" formats
            if ref.startswith('urn:uuid:'):
                med_id = ref.replace('urn:uuid:', '')
            elif '/' in ref:
                med_id = ref.split('/')[-1]
            else:
                med_id = ref

            # Check if this Medication exists in our map
            if med_id in med_map:
                # Add display if missing
                if 'display' not in med_ref or not med_ref['display']:
                    med_ref['display'] = med_map[med_id]['name']
                    display_added_count += 1

                # Fix urn:uuid references to use proper Medication/ format
                # The Medication resource ID might still be a UUID if it wasn't converted
                if ref.startswith('urn:uuid:'):
                    # Keep the UUID format but ensure display is present
                    # The Medication resource should exist with this UUID ID
                    pass  # Reference is fine, just needed display

            continue

        # Case 2: Has medicationCodeableConcept - create Medication resource and convert to Reference
        if 'medicationCodeableConcept' not in resource:
            continue

        med_cc = resource['medicationCodeableConcept']

        # Extract medication display name from CodeableConcept
        # Priority: text field > coding[0].display > fallback
        display = med_cc.get('text')
        if not display and 'coding' in med_cc and med_cc['coding']:
            display = med_cc['coding'][0].get('display', '')

        if not display:
            # Fallback: use resource ID if no display available
            display = f"Medication-{resource.get('id', 'unknown')}"
            print(f"  ⚠️  Warning: No display name found for MedicationRequest/{resource.get('id')}, using fallback")

        # Generate Medication resource ID with 'med-' prefix
        resource_id = resource.get('id', 'unknown')
        med_id = f"med-{resource_id}"

        # Create a new Medication resource with EXACTLY the same structure as Synthea-generated ones
        # Based on analysis of existing Medication resources in the bundle
        medication_resource = {
            "resourceType": "Medication",
            "id": med_id,
            "meta": {
                "profile": [
                    "http://hl7.org/fhir/us/core/StructureDefinition/us-core-medication"
                ],
                "source": "https://www.thetarho.com/fhir",
                "security": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
                        "code": "HTEST",
                        "display": "test health data"
                    }
                ]
            },
            "code": med_cc.copy(),  # Use the entire CodeableConcept from MedicationRequest
            "status": "active"
        }

        # Add athenaHealth extensions (same pattern as other resources)
        if practice_org_id:
            medication_resource["extension"] = [
                {
                    "url": "https://fhir.athena.io/StructureDefinition/ah-practice",
                    "valueReference": {
                        "reference": f"Organization/{practice_org_id}"
                    }
                },
                {
                    "url": "https://fhir.athena.io/StructureDefinition/ah-chart-sharing-group",
                    "valueReference": {
                        "reference": f"Organization/{practice_org_id}"
                    }
                },
                {
                    "url": "athenaId",
                    "valueString": f"{practice_id}.medication-{med_id}"
                }
            ]

            # Add identifier
            medication_resource["identifier"] = [
                {
                    "system": "https://www.thetarho.com/fhir/identifiers/athena",
                    "value": f"{practice_id}.medication-{med_id}"
                }
            ]

        # Create bundle entry for the new Medication resource
        medication_entry = {
            "resource": medication_resource,
            "request": {
                "method": "PUT",
                "url": f"Medication/{med_id}"
            }
        }

        new_medication_entries.append(medication_entry)
        medications_created += 1

        # Create medicationReference with display field
        resource['medicationReference'] = {
            'reference': f'Medication/{med_id}',
            'display': display
        }

        # Remove medicationCodeableConcept to avoid confusion
        del resource['medicationCodeableConcept']

        converted_count += 1

    # Add new Medication resources to bundle
    if new_medication_entries:
        bundle['entry'].extend(new_medication_entries)

    print(f"Converted {converted_count} MedicationRequest resources from CodeableConcept to Reference")
    if medications_created > 0:
        print(f"Created {medications_created} new Medication resources")
    if display_added_count > 0:
        print(f"Added display to {display_added_count} existing medicationReference fields")


def enhance_medication_requests_with_dosage_and_dates(bundle: Dict[str, Any]) -> None:
    """
    Add dosage text and start/end dates to MedicationRequest resources.

    FhirQueryService.java:3445-3452 expects dosageInstruction[].text for dosage display
    FhirQueryService.java:3469-3483 expects note[] with "START_DATE:" and "STOP_DATE:" prefixes

    This function:
    1. Generates human-readable dosage text from structured timing/dose data
    2. Adds START_DATE and STOP_DATE notes based on authoredOn
    3. Adds dispenseRequest.validityPeriod for date range

    Args:
        bundle: FHIR bundle containing MedicationRequest resources
    """
    print("\nEnhancing MedicationRequests with dosage text and dates...")

    enhanced_count = 0

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})

        if resource.get('resourceType') != 'MedicationRequest':
            continue

        medication_id = resource.get('id', 'unknown')
        status = resource.get('status', 'unknown')

        # Only process active medications
        if status != 'active':
            continue

        # Generate dosage text from structured data
        dosage_instructions = resource.get('dosageInstruction', [])
        for dosage in dosage_instructions:
            # Extract structured dosage information
            dose_quantity = None
            dose_unit = ""
            frequency = None
            period = None
            period_unit = ""

            # Get dose quantity
            dose_and_rate = dosage.get('doseAndRate', [])
            if dose_and_rate:
                dose_qty_obj = dose_and_rate[0].get('doseQuantity', {})
                dose_quantity = dose_qty_obj.get('value')
                dose_unit = dose_qty_obj.get('unit', '')

            # Get timing information
            timing = dosage.get('timing', {})
            repeat = timing.get('repeat', {})
            frequency = repeat.get('frequency')
            period = repeat.get('period')
            period_unit = repeat.get('periodUnit', '')

            # Generate human-readable dosage text
            dosage_parts = []

            if dose_quantity:
                if dose_quantity == int(dose_quantity):
                    dose_str = str(int(dose_quantity))
                else:
                    dose_str = str(dose_quantity)

                if dose_unit:
                    dosage_parts.append(f"{dose_str} {dose_unit}")
                else:
                    dosage_parts.append(f"{dose_str} tablet" if dose_quantity == 1 else f"{dose_str} tablets")

            if frequency and period:
                if period_unit == 'd':
                    period_text = 'day'
                elif period_unit == 'h':
                    period_text = 'hour'
                elif period_unit == 'wk':
                    period_text = 'week'
                else:
                    period_text = period_unit

                if frequency == 1 and period == 1.0:
                    dosage_parts.append(f"once per {period_text}")
                elif frequency == 2 and period == 1.0:
                    dosage_parts.append(f"twice per {period_text}")
                else:
                    dosage_parts.append(f"{int(frequency)} times per {period_text}")

            # Add text field to dosageInstruction
            if dosage_parts:
                dosage_text = ", ".join(dosage_parts)
                dosage['text'] = dosage_text
            else:
                dosage['text'] = "Take as directed"

        # Add START_DATE and STOP_DATE to notes
        authored_on = resource.get('authoredOn')
        if authored_on:
            # Parse authoredOn date
            from datetime import datetime, timedelta
            try:
                # Parse ISO format date
                authored_date = datetime.fromisoformat(authored_on.replace('Z', '+00:00'))
                start_date_str = authored_date.strftime('%Y-%m-%d')

                # For active medications, no stop date (ongoing)
                # If status was 'completed', we could add stop date 90 days later

                # Ensure note array exists
                if 'note' not in resource:
                    resource['note'] = []

                # Add START_DATE note
                resource['note'].append({
                    "text": f"START_DATE: {start_date_str}"
                })

                # Calculate realistic end date based on medication type
                # For active chronic medications: use current date + 1 year (ongoing prescriptions)
                # This ensures medications prescribed in the past are still considered "active"
                # if they were meant to be ongoing chronic medications

                # Calculate time elapsed since medication was authored
                from datetime import datetime as dt
                now = dt.now(authored_date.tzinfo) if authored_date.tzinfo else dt.now()
                time_since_authored = now - authored_date

                # If medication was authored more than 1 year ago, set end date to now + 1 year
                # If medication was authored recently, set end date to authored + 2 years
                # This creates realistic validity periods for prescriptions
                if time_since_authored.days > 365:
                    # Old medication still active - extend validity to future
                    end_date = now + timedelta(days=365)  # Valid for 1 more year from now
                else:
                    # Recent medication - standard 2-year prescription validity
                    end_date = authored_date + timedelta(days=730)  # 2 years from prescription

                end_date_str = end_date.isoformat()

                # Add dispenseRequest with validity period including end date
                resource['dispenseRequest'] = {
                    "validityPeriod": {
                        "start": authored_on,
                        "end": end_date_str  # Realistic end date for prescription validity
                    }
                }

                enhanced_count += 1

            except Exception as e:
                print(f"  ⚠️  Warning: Could not parse date for MedicationRequest/{medication_id}: {e}")

    print(f"Enhanced {enhanced_count} MedicationRequest resources with dosage text and dates")


def generate_observations_for_diagnostic_reports(bundle: Dict[str, Any]) -> None:
    """
    Generate comprehensive Observation resources for DiagnosticReport panels.

    Since Synthea doesn't export inline observations, this function generates
    observations based on standard panel definitions (CBC, CMP, Lipid, BMP, etc.).

    Args:
        bundle: FHIR bundle containing DiagnosticReport resources
    """
    import random

    # Counter for generating unique alphanumeric Observation IDs
    obs_id_counter = ID_RANGES['Observation'][0]

    # Standard panel definitions with their constituent observations
    PANEL_DEFINITIONS = {
        # CBC - Complete Blood Count
        "58410-2": {
            "name": "Complete blood count (hemogram) panel - Blood by Automated count",
            "observations": [
                {"code": "6690-2", "display": "Leukocytes [#/volume] in Blood by Automated count", "low": 6.2, "high": 8.5, "unit": "10*3/uL"},
                {"code": "789-8", "display": "Erythrocytes [#/volume] in Blood by Automated count", "low": 4.5, "high": 5.2, "unit": "10*6/uL"},
                {"code": "718-7", "display": "Hemoglobin [Mass/volume] in Blood", "low": 14.0, "high": 16.5, "unit": "g/dL"},
                {"code": "20570-8", "display": "Hematocrit [Volume Fraction] of Blood", "low": 42.0, "high": 48.0, "unit": "%"},
                {"code": "787-2", "display": "MCV [Entitic volume] by Automated count", "low": 85.0, "high": 92.0, "unit": "fL"},
                {"code": "785-6", "display": "MCH [Entitic mass] by Automated count", "low": 28.0, "high": 31.0, "unit": "pg"},
                {"code": "786-4", "display": "MCHC [Mass/volume] by Automated count", "low": 33.0, "high": 35.0, "unit": "g/dL"},
                {"code": "21000-5", "display": "Erythrocyte distribution width [Ratio] by Automated count", "low": 12.5, "high": 14.0, "unit": "%"},
                {"code": "788-0", "display": "Erythrocyte distribution width [Entitic volume] by Automated count", "low": 40.0, "high": 50.0, "unit": "fL"},
                {"code": "777-3", "display": "Platelets [#/volume] in Blood by Automated count", "low": 220.0, "high": 320.0, "unit": "10*3/uL"},
                {"code": "32623-1", "display": "Platelet mean volume [Entitic volume] in Blood by Automated count", "low": 9.5, "high": 11.5, "unit": "fL"},
                {"code": "751-8", "display": "Neutrophils [#/volume] in Blood by Automated count", "low": 3.5, "high": 5.5, "unit": "10*3/uL"},
                {"code": "770-8", "display": "Neutrophils/100 leukocytes in Blood by Automated count", "low": 55.0, "high": 68.0, "unit": "%"},
                {"code": "731-0", "display": "Lymphocytes [#/volume] in Blood by Automated count", "low": 1.5, "high": 2.5, "unit": "10*3/uL"},
                {"code": "736-9", "display": "Lymphocytes/100 leukocytes in Blood by Automated count", "low": 22.0, "high": 32.0, "unit": "%"},
                {"code": "742-7", "display": "Monocytes [#/volume] in Blood by Automated count", "low": 0.4, "high": 0.7, "unit": "10*3/uL"},
                {"code": "5905-5", "display": "Monocytes/100 leukocytes in Blood by Automated count", "low": 5.0, "high": 9.0, "unit": "%"},
                {"code": "711-2", "display": "Eosinophils [#/volume] in Blood by Automated count", "low": 0.1, "high": 0.3, "unit": "10*3/uL"},
                {"code": "713-8", "display": "Eosinophils/100 leukocytes in Blood by Automated count", "low": 1.0, "high": 3.5, "unit": "%"},
                {"code": "706-2", "display": "Basophils/100 leukocytes in Blood by Automated count", "low": 0.3, "high": 0.8, "unit": "%"},
            ]
        },
        # CMP - Comprehensive Metabolic Panel
        "24323-8": {
            "name": "Comprehensive metabolic 2000 panel - Serum or Plasma",
            "observations": [
                {"code": "2345-7", "display": "Glucose [Mass/volume] in Serum or Plasma", "low": 110, "high": 140, "unit": "mg/dL"},
                {"code": "2160-0", "display": "Creatinine [Mass/volume] in Serum or Plasma", "low": 0.9, "high": 1.1, "unit": "mg/dL"},
                {"code": "6299-2", "display": "Urea nitrogen [Mass/volume] in Blood", "low": 12, "high": 18, "unit": "mg/dL"},
                {"code": "2951-2", "display": "Sodium [Moles/volume] in Serum or Plasma", "low": 138, "high": 142, "unit": "mmol/L"},
                {"code": "2823-3", "display": "Potassium [Moles/volume] in Serum or Plasma", "low": 3.8, "high": 4.5, "unit": "mmol/L"},
                {"code": "2075-0", "display": "Chloride [Moles/volume] in Serum or Plasma", "low": 100, "high": 106, "unit": "mmol/L"},
                {"code": "2028-9", "display": "Carbon dioxide, total [Moles/volume] in Serum or Plasma", "low": 23, "high": 28, "unit": "mmol/L"},
                {"code": "17861-6", "display": "Calcium [Mass/volume] in Serum or Plasma", "low": 9.2, "high": 10.0, "unit": "mg/dL"},
                {"code": "1975-2", "display": "Bilirubin.total [Mass/volume] in Serum or Plasma", "low": 0.4, "high": 0.8, "unit": "mg/dL"},
                {"code": "1742-6", "display": "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma", "low": 20, "high": 35, "unit": "U/L"},
                {"code": "1920-8", "display": "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma", "low": 18, "high": 32, "unit": "U/L"},
                {"code": "6768-6", "display": "Alkaline phosphatase [Enzymatic activity/volume] in Serum or Plasma", "low": 45, "high": 85, "unit": "U/L"},
                {"code": "2885-2", "display": "Protein [Mass/volume] in Serum or Plasma", "low": 6.8, "high": 7.5, "unit": "g/dL"},
                {"code": "1751-7", "display": "Albumin [Mass/volume] in Serum or Plasma", "low": 4.0, "high": 4.8, "unit": "g/dL"},
            ]
        },
        # Lipid Panel
        "57698-3": {
            "name": "Lipid panel with direct LDL - Serum or Plasma",
            "observations": [
                {"code": "2093-3", "display": "Cholesterol [Mass/volume] in Serum or Plasma", "low": 195, "high": 230, "unit": "mg/dL"},
                {"code": "18262-6", "display": "Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay", "low": 125, "high": 155, "unit": "mg/dL"},
                {"code": "2085-9", "display": "Cholesterol in HDL [Mass/volume] in Serum or Plasma", "low": 45, "high": 55, "unit": "mg/dL"},
                {"code": "2571-8", "display": "Triglyceride [Mass/volume] in Serum or Plasma", "low": 140, "high": 180, "unit": "mg/dL"},
            ]
        },
        # BMP - Basic Metabolic Panel
        "51990-0": {
            "name": "Basic metabolic panel - Blood",
            "observations": [
                {"code": "2345-7", "display": "Glucose [Mass/volume] in Serum or Plasma", "low": 145, "high": 165, "unit": "mg/dL"},
                {"code": "2160-0", "display": "Creatinine [Mass/volume] in Serum or Plasma", "low": 0.9, "high": 1.1, "unit": "mg/dL"},
                {"code": "6299-2", "display": "Urea nitrogen [Mass/volume] in Blood", "low": 13, "high": 19, "unit": "mg/dL"},
                {"code": "2951-2", "display": "Sodium [Moles/volume] in Serum or Plasma", "low": 138, "high": 142, "unit": "mmol/L"},
                {"code": "2823-3", "display": "Potassium [Moles/volume] in Serum or Plasma", "low": 3.8, "high": 4.5, "unit": "mmol/L"},
                {"code": "2075-0", "display": "Chloride [Moles/volume] in Serum or Plasma", "low": 100, "high": 106, "unit": "mmol/L"},
                {"code": "2028-9", "display": "Carbon dioxide, total [Moles/volume] in Serum or Plasma", "low": 23, "high": 28, "unit": "mmol/L"},
                {"code": "17861-6", "display": "Calcium [Mass/volume] in Serum or Plasma", "low": 9.2, "high": 10.0, "unit": "mg/dL"},
            ]
        },
        # HbA1c
        "4548-4": {
            "name": "Hemoglobin A1c/Hemoglobin.total in Blood",
            "observations": [
                {"code": "4548-4", "display": "Hemoglobin A1c/Hemoglobin.total in Blood", "low": 7.8, "high": 8.2, "unit": "%"},
            ]
        },
    }

    new_observations = []
    dr_count = 0

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') != 'DiagnosticReport':
            continue

        # Get panel code
        code_obj = resource.get('code', {})
        codings = code_obj.get('coding', [])
        if not codings:
            continue

        panel_code = codings[0].get('code', '')
        if panel_code not in PANEL_DEFINITIONS:
            continue

        panel_def = PANEL_DEFINITIONS[panel_code]

        # Extract metadata from DiagnosticReport
        dr_encounter = resource.get('encounter', {})
        dr_subject = resource.get('subject', {})
        dr_effective = resource.get('effectiveDateTime', '')
        dr_issued = resource.get('issued', '')

        # Generate observations for this panel
        for obs_def in panel_def['observations']:
            # Generate alphanumeric ID from Observation ID range
            obs_id = f"{ID_PREFIXES['Observation']}{obs_id_counter}"
            obs_id_counter += 1

            # Generate random value within range
            value = round(random.uniform(obs_def['low'], obs_def['high']), 2)

            observation = {
                'resourceType': 'Observation',
                'id': obs_id,
                'status': 'final',
                'category': [
                    {
                        'coding': [
                            {
                                'system': 'http://terminology.hl7.org/CodeSystem/observation-category',
                                'code': 'laboratory',
                                'display': 'Laboratory'
                            }
                        ]
                    }
                ],
                'code': {
                    'coding': [
                        {
                            'system': 'http://loinc.org',
                            'code': obs_def['code'],
                            'display': obs_def['display']
                        }
                    ],
                    'text': obs_def['display']
                },
                'subject': dr_subject.copy() if dr_subject else {},
                'encounter': dr_encounter.copy() if dr_encounter else {},
                'effectiveDateTime': dr_effective,
                'issued': dr_issued,
                'valueQuantity': {
                    'value': value,
                    'unit': obs_def['unit'],
                    'system': 'http://unitsofmeasure.org',
                    'code': obs_def['unit']
                },
                'referenceRange': [
                    {
                        'low': {
                            'value': obs_def['low'],
                            'unit': obs_def['unit'],
                            'system': 'http://unitsofmeasure.org',
                            'code': obs_def['unit']
                        },
                        'high': {
                            'value': obs_def['high'],
                            'unit': obs_def['unit'],
                            'system': 'http://unitsofmeasure.org',
                            'code': obs_def['unit']
                        }
                    }
                ]
            }

            # Create bundle entry
            new_obs_entry = {
                'fullUrl': f'Observation/{obs_id}',
                'resource': observation,
                'request': {
                    'method': 'POST',
                    'url': 'Observation'
                }
            }

            new_observations.append(new_obs_entry)

        dr_count += 1

    # Add new observations to bundle
    if new_observations:
        bundle['entry'].extend(new_observations)
        print(f"Generated {len(new_observations)} observations for {dr_count} DiagnosticReport panels")


def link_observations_to_diagnostic_reports(bundle: Dict[str, Any]) -> None:
    """
    Link Observation resources to DiagnosticReport resources by populating result[] arrays.

    TRDataServices expects DiagnosticReport.result[] to contain references to observations.
    FhirQueryService.java:3620-3623 processes diagnosticReport.getResult() and fetches
    the referenced observations to populate TRDiagnosticReport.observations list.

    This function analyzes the bundle structure and links observations to diagnostic reports based on:
    1. Same encounter reference
    2. Temporal proximity (observations created near the DiagnosticReport timestamp)
    3. LOINC code matching for panel types (CBC, CMP, Lipid, etc.)

    Args:
        bundle: FHIR bundle containing DiagnosticReport and Observation resources
    """
    from datetime import datetime, timedelta
    from typing import List, Dict

    # Build index of observations by encounter and timestamp
    observations_by_encounter = {}
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') != 'Observation':
            continue

        obs_id = resource.get('id')
        encounter_ref = resource.get('encounter', {}).get('reference', '')
        effective = resource.get('effectiveDateTime', '')
        category = resource.get('category', [])
        category_code = category[0].get('coding', [{}])[0].get('code') if category else None

        # Only link laboratory observations
        if category_code != 'laboratory':
            continue

        if encounter_ref:
            if encounter_ref not in observations_by_encounter:
                observations_by_encounter[encounter_ref] = []
            observations_by_encounter[encounter_ref].append({
                'id': obs_id,
                'fullUrl': entry.get('fullUrl', f'urn:uuid:{obs_id}'),
                'effective': effective,
                'resource': resource
            })

    # Process DiagnosticReports and link observations
    linked_count = 0
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') != 'DiagnosticReport':
            continue

        encounter_ref = resource.get('encounter', {}).get('reference', '')
        if not encounter_ref:
            continue

        dr_effective = resource.get('effectiveDateTime', '')
        dr_code = resource.get('code', {})
        dr_loinc = None
        for coding in dr_code.get('coding', []):
            if coding.get('system') == 'LOINC':
                dr_loinc = coding.get('code')
                break

        # Get observations from same encounter
        encounter_obs = observations_by_encounter.get(encounter_ref, [])
        if not encounter_obs:
            continue

        # For observations created in same encounter, link them to the DiagnosticReport
        # Strategy: observations created just before the DiagnosticReport timestamp
        # are likely part of that diagnostic panel

        # Parse timestamps to find observations within reasonable timeframe
        linked_obs = []
        try:
            dr_time = datetime.fromisoformat(dr_effective.replace('Z', '+00:00')) if dr_effective else None
        except:
            dr_time = None

        for obs_data in encounter_obs:
            obs_effective = obs_data['effective']
            try:
                obs_time = datetime.fromisoformat(obs_effective.replace('Z', '+00:00')) if obs_effective else None
            except:
                obs_time = None

            # If we have timestamps, only link observations within 1 hour of the DiagnosticReport
            # If no timestamps, link all observations from the same encounter
            should_link = False
            if dr_time and obs_time:
                time_diff = abs((dr_time - obs_time).total_seconds())
                # Observations within 1 hour (3600 seconds) of the DiagnosticReport
                if time_diff <= 3600:
                    should_link = True
            elif dr_effective == obs_effective:
                # Same timestamp - definitely linked
                should_link = True
            elif not dr_effective or not obs_effective:
                # No timestamp info - link all laboratory observations from same encounter
                should_link = True

            if should_link:
                linked_obs.append(obs_data)

        # Populate result array with observation references
        if linked_obs and 'result' not in resource:
            resource['result'] = []

        for obs_data in linked_obs:
            # Create reference object
            obs_resource = obs_data['resource']
            obs_display = obs_resource.get('code', {}).get('text') or \
                         (obs_resource.get('code', {}).get('coding', [{}])[0].get('display') if obs_resource.get('code', {}).get('coding') else '')

            obs_ref = {
                'reference': f"Observation/{obs_data['id']}"
            }
            if obs_display:
                obs_ref['display'] = obs_display

            # Add to result array if not already present
            if obs_ref not in resource.get('result', []):
                resource['result'].append(obs_ref)
                linked_count += 1

    print(f"Linked {linked_count} observations to DiagnosticReport.result arrays")


def add_service_provider_display(bundle: Dict[str, Any]) -> None:
    """
    Add display field to Encounter.serviceProvider references.

    FhirQueryService.java:2338-2343 expects serviceProvider.display for hospital names
    in ER/UrgentCare visit sections. Synthea generates references without display.

    This function:
    1. Builds a map of Organization ID -> name
    2. Adds display field to Encounter.serviceProvider using Organization name

    Args:
        bundle: FHIR bundle containing Encounter and Organization resources
    """
    # Build organization ID to name mapping from bundle
    org_map = {}
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') == 'Organization':
            org_id = resource.get('id')
            name = resource.get('name', 'Unknown Organization')
            if org_id:
                org_map[org_id] = name

    if not org_map:
        print("No Organization resources found in bundle - cannot add serviceProvider display")
        return

    # Add display to Encounter.serviceProvider references
    updated_count = 0
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') != 'Encounter':
            continue

        if 'serviceProvider' in resource:
            sp = resource['serviceProvider']

            # Only add if display doesn't already exist
            if 'reference' in sp and 'display' not in sp:
                # Extract Organization ID from reference (e.g., "Organization/t8008926" -> "t8008926")
                ref = sp['reference']
                org_id = ref.split('/')[-1] if '/' in ref else ref

                # Look up organization name
                if org_id in org_map:
                    sp['display'] = org_map[org_id]
                    updated_count += 1

    if updated_count > 0:
        print(f"Added serviceProvider display to {updated_count} Encounter resources")


def process_ccda_xml(input_file: str, uuid_map: Dict[str, Tuple[str, str]], output_dir: str, patient_id: str, practice_id: str = None) -> None:
    """
    Process CCDA XML file and update all UUID references to use alphanumeric test IDs.
    Also adds simple patient identifier for TRDataServices compatibility.

    Args:
        input_file: Path to the original FHIR bundle (to find corresponding CCDA)
        uuid_map: Dictionary mapping UUID -> (alphanumeric_id, resource_type)
        output_dir: Directory to save the updated CCDA XML
        patient_id: Base patient ID (e.g., "1000000")
        practice_id: Practice identifier (e.g., "a-16349")
    """
    import xml.etree.ElementTree as ET
    import glob

    # Determine CCDA file path based on input file
    # Synthea generates CCDA in output/ccda/ with same base name
    fhir_filename = os.path.basename(input_file)
    base_name = os.path.splitext(fhir_filename)[0]

    # Look for CCDA file in ccda directory
    ccda_dir = os.path.join(os.path.dirname(os.path.dirname(input_file)), 'ccda')
    ccda_pattern = os.path.join(ccda_dir, f"{base_name}.xml")

    ccda_files = glob.glob(ccda_pattern)

    if not ccda_files:
        print(f"\n  No CCDA XML found at {ccda_pattern}")
        print(f"  Skipping CCDA processing")
        return

    ccda_file = ccda_files[0]
    print(f"\nProcessing CCDA XML...")
    print(f"  Input: {ccda_file}")

    # Parse XML using ElementTree to modify structure
    ET.register_namespace('', 'urn:hl7-org:v3')
    ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
    ET.register_namespace('sdtc', 'urn:hl7-org:sdtc')

    tree = ET.parse(ccda_file)
    root = tree.getroot()

    # Define namespace
    ns = {'hl7': 'urn:hl7-org:v3'}

    # Find the recordTarget/patientRole section
    patient_role = root.find('.//hl7:recordTarget/hl7:patientRole', ns)

    if patient_role is not None:
        # Find existing patient IDs
        existing_ids = patient_role.findall('hl7:id', ns)

        # Check if simple patient ID already exists
        has_simple_id = False
        for id_elem in existing_ids:
            if id_elem.get('extension') == f"t{patient_id}":
                has_simple_id = True
                break

        # Add simple patient identifier if not present
        if not has_simple_id:
            # Create new id element with simple patient ID
            new_id = ET.Element('{urn:hl7-org:v3}id')
            new_id.set('root', '2.16.840.1.113883.3.1234.5.1')  # ThetaRho patient identifier system
            new_id.set('extension', f"t{patient_id}")
            new_id.set('assigningAuthorityName', 'https://www.thetarho.com/fhir/identifiers/patient')

            # Insert after the first id element (which has the synthea UUID)
            if existing_ids:
                idx = list(patient_role).index(existing_ids[0]) + 1
                patient_role.insert(idx, new_id)
                print(f"  ✓ Added simple patient identifier: t{patient_id}")

    # Convert tree back to string for UUID replacement
    xml_content = ET.tostring(root, encoding='unicode', method='xml')

    # Track replacements
    replacements_made = 0

    # Replace all UUIDs with alphanumeric IDs
    for uuid, (alphanumeric_id, resource_type) in uuid_map.items():
        # Skip if the uuid is already alphanumeric (shouldn't happen but safety check)
        if uuid.startswith('t'):
            continue

        # Count occurrences
        count = xml_content.count(uuid)
        if count > 0:
            xml_content = xml_content.replace(uuid, alphanumeric_id)
            replacements_made += count
            if count > 0:
                print(f"    Replaced {uuid} -> {alphanumeric_id} ({count} occurrences)")

    # Save updated CCDA XML
    output_ccda = os.path.join(output_dir, f"t{patient_id}_ccda.xml")
    with open(output_ccda, 'w+', encoding='utf-8') as f:
        f.write(xml_content)

    print(f"  ✓ Saved updated CCDA XML to {os.path.basename(output_ccda)}")
    print(f"  ✓ Total replacements: {replacements_made}")


def save_shared_resources(bundle: Dict[str, Any], output_dir: str) -> None:
    """
    Extract and save shared resources (Organization, Practitioner, Location, PractitionerRole) to separate files.
    These resources can be shared across multiple patients.

    Args:
        bundle: FHIR transaction bundle
        output_dir: Directory to save shared resource files
    """
    shared_resource_types = ['Organization', 'Practitioner', 'Location', 'PractitionerRole']
    shared_resources = {resource_type: [] for resource_type in shared_resource_types}

    # Extract shared resources from bundle
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')

        if resource_type in shared_resource_types:
            shared_resources[resource_type].append(resource)

    # Save each resource type to a separate file
    for resource_type, resources in shared_resources.items():
        if resources:
            # Create FHIR transaction Bundle with PUT requests for each resource
            # This ensures FHIR server uses the specified IDs instead of auto-generating them
            entries = []
            for resource in resources:
                entry = {"resource": resource}
                # Add request metadata for transaction processing
                if 'id' in resource:
                    entry['request'] = {
                        'method': 'PUT',
                        'url': f"{resource_type}/{resource['id']}"
                    }
                entries.append(entry)

            resource_bundle = {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": entries
            }

            # Save to file
            filename = f"{resource_type}.json"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w') as f:
                json.dump(resource_bundle, f, indent=2)

            print(f"  ✓ Saved {len(resources)} {resource_type} resource(s) to {filename}")


def load_additional_bundles(patient_bundle_path: str) -> List[Dict[str, Any]]:
    """
    Load Practitioner and Organization bundles from the same directory.

    Args:
        patient_bundle_path: Path to the patient FHIR bundle

    Returns:
        List of additional bundles (Practitioner, Organization)
    """
    import os
    import glob

    directory = os.path.dirname(patient_bundle_path)
    additional_bundles = []

    # Look for practitionerInformation*.json and hospitalInformation*.json
    practitioner_files = glob.glob(os.path.join(directory, "practitionerInformation*.json"))
    hospital_files = glob.glob(os.path.join(directory, "hospitalInformation*.json"))

    for file_path in practitioner_files + hospital_files:
        print(f"  Loading additional bundle: {os.path.basename(file_path)}")
        with open(file_path, 'r') as f:
            additional_bundles.append(json.load(f))

    return additional_bundles


def merge_bundles(main_bundle: Dict[str, Any], additional_bundles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge additional bundles (Practitioner, Organization) into main patient bundle.

    Args:
        main_bundle: Main patient FHIR bundle
        additional_bundles: List of additional bundles to merge

    Returns:
        Merged bundle with all resources
    """
    merged_bundle = main_bundle.copy()

    for bundle in additional_bundles:
        for entry in bundle.get('entry', []):
            # Add the resource to the main bundle
            merged_bundle['entry'].append(entry)

    return merged_bundle


def add_general_practitioner_to_patient(bundle: Dict[str, Any]) -> None:
    """
    Add generalPractitioner reference to Patient resource.

    CRITICAL: HTMLService.java:674-785 extracts practitioner ID from Patient.generalPractitioner
    for mock patients. This function ensures the Patient resource has a valid reference to the
    first Practitioner in the bundle.

    Args:
        bundle: FHIR transaction bundle
    """
    print("\n=== Adding generalPractitioner to Patient ===")

    patient = None
    patient_id = None
    practitioner_id = None

    # Find Patient and first Practitioner
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')

        if resource_type == 'Patient':
            patient = resource
            patient_id = resource.get('id')
        elif resource_type == 'Practitioner' and practitioner_id is None:
            practitioner_id = resource.get('id')

    if not patient:
        print("⚠️  No Patient resource found in bundle")
        return

    if not practitioner_id:
        print("⚠️  No Practitioner resource found in bundle")
        print("    Patient will not have generalPractitioner reference")
        return

    # Add generalPractitioner reference
    patient['generalPractitioner'] = [
        {
            "reference": f"Practitioner/{practitioner_id}",
            "type": "Practitioner"
        }
    ]

    print(f"✅ Added generalPractitioner reference to Patient/{patient_id}")
    print(f"   Reference: Practitioner/{practitioner_id}")


def interpret_lab_value(obs_name, value, unit):
    """
    Interpret lab values and return normal/abnormal flag with clinical significance.

    Returns tuple: (flag, interpretation)
    - flag: 'N' (normal), 'H' (high), 'L' (low), 'C' (critical)
    - interpretation: clinical significance string
    """
    obs_lower = obs_name.lower()

    # Reference ranges and interpretations
    ranges = {
        'glucose': {'low': 70, 'high': 100, 'critical_high': 200, 'unit': 'mg/dL'},
        'hemoglobin a1c': {'high': 5.7, 'critical_high': 7.0, 'unit': '%'},
        'hemoglobin': {'low': 12.0, 'high': 16.0, 'unit': 'g/dL'},
        'hematocrit': {'low': 36.0, 'high': 46.0, 'unit': '%'},
        'wbc': {'low': 4.0, 'high': 11.0, 'unit': '10*3/uL'},
        'platelet': {'low': 150, 'high': 400, 'unit': '10*3/uL'},
        'cholesterol': {'high': 200, 'critical_high': 240, 'unit': 'mg/dL'},
        'ldl': {'high': 100, 'critical_high': 160, 'unit': 'mg/dL'},
        'hdl': {'low': 40, 'unit': 'mg/dL'},
        'triglyceride': {'high': 150, 'critical_high': 200, 'unit': 'mg/dL'},
        'systolic': {'high': 120, 'critical_high': 140, 'unit': 'mm[Hg]'},
        'diastolic': {'high': 80, 'critical_high': 90, 'unit': 'mm[Hg]'},
        'bmi': {'high': 25.0, 'critical_high': 30.0, 'unit': 'kg/m2'},
        'tsh': {'low': 0.4, 'high': 4.0, 'unit': 'm[IU]/L'},
    }

    try:
        value_num = float(value)
    except (ValueError, TypeError):
        return 'N', ''

    # Find matching reference range
    for key, ref in ranges.items():
        if key in obs_lower:
            # Check critical values
            if 'critical_high' in ref and value_num >= ref['critical_high']:
                if 'glucose' in key:
                    return 'C', 'Significantly elevated - diabetes poorly controlled'
                elif 'a1c' in key:
                    return 'C', 'Poor glycemic control'
                elif 'cholesterol' in key or 'ldl' in key:
                    return 'C', 'Significantly elevated - high cardiovascular risk'
                elif 'systolic' in key or 'diastolic' in key:
                    return 'C', 'Stage 2 hypertension'
                elif 'bmi' in key:
                    return 'C', 'Obesity'
                return 'C', 'Critically high'

            # Check high values
            if 'high' in ref and value_num > ref['high']:
                if 'glucose' in key:
                    return 'H', 'Elevated - prediabetic range'
                elif 'a1c' in key:
                    return 'H', 'Above goal'
                elif 'cholesterol' in key or 'ldl' in key:
                    return 'H', 'Elevated - cardiovascular risk'
                elif 'bmi' in key:
                    return 'H', 'Overweight'
                return 'H', 'Above normal'

            # Check low values
            if 'low' in ref and value_num < ref['low']:
                if 'glucose' in key:
                    return 'L', 'Hypoglycemia risk'
                elif 'hemoglobin' in key or 'hematocrit' in key:
                    return 'L', 'Anemia'
                elif 'hdl' in key:
                    return 'L', 'Suboptimal - increased cardiovascular risk'
                return 'L', 'Below normal'

            # Normal range
            return 'N', 'Within normal limits'

    return 'N', ''


def generate_clinical_narrative_for_encounter(encounter, conditions, observations, medications,
                                              diagnostic_reports, encounter_type, patient_resource=None,
                                              all_medications=None, encounter_index=0):
    """
    Generate context-aware clinical narrative for specific encounter types.

    Provides clinically accurate, detailed progress notes tailored to the encounter context
    with patient-specific details, lab interpretations, and medication reconciliation.

    Args:
        encounter: Encounter resource
        conditions: List of Condition resources for this encounter
        observations: List of Observation resources for this encounter
        medications: List of MedicationRequest resources for this encounter
        diagnostic_reports: List of DiagnosticReport resources for this encounter
        encounter_type: Display name of encounter type
        patient_resource: Patient resource (for name, age, gender)
        all_medications: All MedicationRequest resources for patient (for reconciliation)
        encounter_index: Index of this encounter in chronological order

    Returns:
        HTML-formatted clinical narrative with escaped XML entities
    """
    import html
    from datetime import datetime

    narrative_parts = []

    # Extract patient demographics
    patient_age = "middle-aged"
    patient_gender = "patient"
    patient_name = "Patient"

    if patient_resource:
        # Calculate age
        if patient_resource.get('birthDate'):
            try:
                from datetime import date
                birth_date = datetime.fromisoformat(patient_resource['birthDate'].replace('Z', '+00:00'))
                today = date.today()
                age_years = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
                patient_age = str(age_years)
            except:
                patient_age = "middle-aged"

        # Get gender
        gender = patient_resource.get('gender', '').lower()
        if gender == 'female':
            patient_gender = "female"
        elif gender == 'male':
            patient_gender = "male"

        # Get patient name
        if patient_resource.get('name') and len(patient_resource['name']) > 0:
            name_obj = patient_resource['name'][0]
            given = ' '.join(name_obj.get('given', []))
            family = name_obj.get('family', '')
            if given and family:
                patient_name = f"{given} {family}"
            elif given:
                patient_name = given
            elif family:
                patient_name = family

    # Detect encounter context based on resources and encounter type
    is_initial_diagnosis = any('diabetes' in c.get('code', {}).get('coding', [{}])[0].get('display', '').lower()
                               for c in conditions) and len(conditions) >= 4
    is_emergency = 'emergency' in encounter_type.lower()
    is_wellness = 'check up' in encounter_type.lower() and len(diagnostic_reports) > 2
    is_procedure = 'procedure' in encounter_type.lower()
    is_hospitalization = 'inpatient' in encounter_type.lower() or 'admission' in encounter_type.lower()
    is_followup_adjustment = any('metformin' in m.get('medicationCodeableConcept', {}).get('coding', [{}])[0].get('display', '').lower() and '1000' in m.get('medicationCodeableConcept', {}).get('coding', [{}])[0].get('display', '')
                                  for m in medications)
    is_insulin_start = any('insulin' in m.get('medicationCodeableConcept', {}).get('coding', [{}])[0].get('display', '').lower()
                           for m in medications)
    has_imaging = any('imaging' in dr.get('category', [{}])[0].get('coding', [{}])[0].get('display', '').lower() if dr.get('category') else False
                      for dr in diagnostic_reports)

    # SUBJECTIVE
    narrative_parts.append("<h3>Subjective:</h3>")

    if is_initial_diagnosis:
        narrative_parts.append(f"<p>{patient_name}, a {patient_age}-year-old {patient_gender}, presents for initial consultation with chief complaints of fatigue, excessive thirst, and unintentional weight changes over the past 3 months. {patient_name} reports increased urinary frequency and occasional blurred vision. Denies chest pain, shortness of breath, or edema. Former smoker (quit 10 years ago), no alcohol use.</p>")
    elif is_emergency:
        narrative_parts.append(f"<p>{patient_name} presents to ED via personal vehicle with complaint of dizziness, tremors, and diaphoresis that started approximately 2 hours ago. Reports skipping breakfast and taking metformin as prescribed. Denies loss of consciousness, chest pain, palpitations. {patient_name} appears anxious but oriented x3.</p>")
    elif is_insulin_start:
        narrative_parts.append(f"<p>{patient_name} returns for diabetes management follow-up 2 weeks post-ED visit for hypoglycemia. Reports better dietary compliance and more consistent meal timing since episode. Checking fingerstick glucose readings 2-3 times daily, averaging 140-165 mg/dL fasting. No further hypoglycemic episodes. Tolerating current medication regimen well.</p>")
    elif is_wellness:
        narrative_parts.append(f"<p>{patient_name}, a {patient_age}-year-old {patient_gender}, here for annual wellness examination and chronic disease management. {patient_name} reports overall feeling well with good energy levels. Diabetes control has improved significantly on current regimen. Blood pressure measurements at home averaging 128/80. Denies chest pain, dyspnea, visual changes, or pedal edema. Medication adherence is excellent.</p>")
    elif is_procedure:
        narrative_parts.append(f"<p>{patient_name} presents for scheduled {encounter_type.lower()}. Pre-procedure assessment completed. {patient_name} tolerated procedure well without complications.</p>")
    elif is_hospitalization:
        narrative_parts.append(f"<p>{patient_name} admitted for {encounter_type.lower()}. Presenting complaint addressed during hospitalization. Clinical course and treatment documented below.</p>")
    elif is_followup_adjustment:
        narrative_parts.append(f"<p>{patient_name} returns for 1-month follow-up after initiation of diabetes and hypertension therapy. Reports improved energy levels but still experiencing some thirst. Tolerating metformin well without significant GI upset. Home glucose readings have decreased from 170s to 150s mg/dL fasting. Blood pressure improved.</p>")
    else:
        narrative_parts.append(f"<p>{patient_name} presents for {encounter_type.lower()}. Chronic conditions stable with ongoing medication management.</p>")

    # OBJECTIVE
    narrative_parts.append("<h3>Objective:</h3>")

    # Vital signs with interpretations
    vital_obs = [o for o in observations if o.get('category', [{}])[0].get('coding', [{}])[0].get('code', '') == 'vital-signs']
    if vital_obs:
        narrative_parts.append("<p><strong>Vital Signs:</strong></p><ul>")
        for obs in vital_obs:
            obs_name = obs.get('code', {}).get('coding', [{}])[0].get('display', 'Unknown')
            value = obs.get('valueQuantity', {}).get('value', '')
            unit = obs.get('valueQuantity', {}).get('unit', '')
            if value:
                flag, interpretation = interpret_lab_value(obs_name, value, unit)
                # Use text descriptors instead of brackets for FHIR XHTML compatibility
                flag_display = {'N': '', 'H': ' <strong>(HIGH)</strong>', 'L': ' <strong>(LOW)</strong>', 'C': ' <strong>(CRITICAL)</strong>'}
                interp_text = f" - {html.escape(interpretation)}" if interpretation else ""
                narrative_parts.append(f"<li>{html.escape(obs_name)}: {value} {unit}{flag_display.get(flag, '')}{interp_text}</li>")
        narrative_parts.append("</ul>")

    # Lab results with interpretations and clinical significance
    lab_obs = [o for o in observations if o.get('category', [{}])[0].get('coding', [{}])[0].get('code', '') == 'laboratory']
    if lab_obs:
        narrative_parts.append("<p><strong>Laboratory Results:</strong></p>")

        # Group by panel type with interpretations
        cbc_results = []
        metabolic_results = []
        lipid_results = []
        other_results = []

        for obs in lab_obs:
            obs_name = obs.get('code', {}).get('coding', [{}])[0].get('display', 'Unknown')
            value = obs.get('valueQuantity', {}).get('value', '')
            unit = obs.get('valueQuantity', {}).get('unit', '')

            if value:
                flag, interpretation = interpret_lab_value(obs_name, value, unit)
                # Use text descriptors instead of brackets for FHIR XHTML compatibility
                flag_display = {'N': '', 'H': ' (H)', 'L': ' (L)', 'C': ' (CRITICAL)'}
                result_line = f"{html.escape(obs_name)} {value} {unit}{flag_display.get(flag, '')}"
            else:
                result_line = html.escape(obs_name)

            if any(term in obs_name.lower() for term in ['hemoglobin', 'hematocrit', 'wbc', 'rbc', 'platelet', 'neutrophil', 'lymphocyte']):
                cbc_results.append((result_line, flag if value else 'N'))
            elif any(term in obs_name.lower() for term in ['glucose', 'sodium', 'potassium', 'creatinine', 'bun', 'a1c']):
                metabolic_results.append((result_line, flag if value else 'N'))
            elif any(term in obs_name.lower() for term in ['cholesterol', 'ldl', 'hdl', 'triglyceride']):
                lipid_results.append((result_line, flag if value else 'N'))
            else:
                other_results.append((result_line, flag if value else 'N'))

        # Display grouped results
        if cbc_results:
            narrative_parts.append("<p><strong>CBC:</strong></p><ul>")
            for result_line, flag in cbc_results[:8]:
                narrative_parts.append(f"<li>{result_line}</li>")
            narrative_parts.append("</ul>")

        if metabolic_results:
            narrative_parts.append("<p><strong>Metabolic Panel:</strong></p><ul>")
            for result_line, flag in metabolic_results[:8]:
                narrative_parts.append(f"<li>{result_line}</li>")
            narrative_parts.append("</ul>")

        if lipid_results:
            narrative_parts.append("<p><strong>Lipid Panel:</strong></p><ul>")
            for result_line, flag in lipid_results:
                narrative_parts.append(f"<li>{result_line}</li>")
            narrative_parts.append("</ul>")

        if other_results:
            narrative_parts.append("<p><strong>Other Labs:</strong></p><ul>")
            for result_line, flag in other_results[:5]:
                narrative_parts.append(f"<li>{result_line}</li>")
            narrative_parts.append("</ul>")

    # Imaging results
    if has_imaging:
        narrative_parts.append("<p><strong>Imaging:</strong></p><ul>")
        for report in diagnostic_reports:
            if report.get('category') and 'imaging' in str(report.get('category')).lower():
                report_name = report.get('code', {}).get('coding', [{}])[0].get('display', 'Unknown imaging study')
                narrative_parts.append(f"<li>{html.escape(report_name)}: No acute abnormalities identified</li>")
        narrative_parts.append("</ul>")

    # ASSESSMENT
    narrative_parts.append("<h3>Assessment:</h3>")
    narrative_parts.append("<ol>")

    if conditions:
        for idx, condition in enumerate(conditions, 1):
            condition_name = condition.get('code', {}).get('coding', [{}])[0].get('display', 'Unknown condition')

            # Add clinical context
            if 'diabetes' in condition_name.lower():
                if is_initial_diagnosis:
                    narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - Newly diagnosed. HbA1c 9.3% indicates poor glycemic control. Patient meets diagnostic criteria.</li>")
                elif is_insulin_start:
                    narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - Suboptimal control on oral agent alone. Recent hypoglycemic episode due to medication-food mismatch.</li>")
                elif is_wellness:
                    narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - Improved control on combination therapy. HbA1c trending toward goal.</li>")
                else:
                    narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - Under active management.</li>")

            elif 'hypertension' in condition_name.lower():
                if is_initial_diagnosis:
                    narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - Stage 2 hypertension (BP 150/94). No evidence of end-organ damage currently.</li>")
                elif is_wellness:
                    narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - Well-controlled on ACE inhibitor therapy. Home readings within target range.</li>")
                else:
                    narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - Stable.</li>")

            elif 'hyperlipidemia' in condition_name.lower():
                if is_initial_diagnosis:
                    narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - Elevated LDL 170 mg/dL, low HDL 38 mg/dL. Increased cardiovascular risk.</li>")
                else:
                    narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - On statin therapy, trending toward LDL goal.</li>")

            elif 'hypothyroidism' in condition_name.lower():
                narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - Subclinical, on levothyroxine replacement. TSH within therapeutic range.</li>")

            elif 'hypoglycemia' in condition_name.lower():
                narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong> - Resolved. Related to medication-food timing mismatch. Patient educated on meal consistency.</li>")
            else:
                narrative_parts.append(f"<li><strong>{html.escape(condition_name)}</strong></li>")
    else:
        narrative_parts.append("<li>No new diagnoses at this visit.</li>")

    narrative_parts.append("</ol>")

    # PLAN
    narrative_parts.append("<h3>Plan:</h3>")
    narrative_parts.append("<ol>")

    if is_initial_diagnosis:
        narrative_parts.append("<li><strong>Diabetes Management:</strong> Initiate metformin 500mg BID with meals. Diabetes education provided regarding diet, exercise, and glucose monitoring. Patient given glucometer and instructed on use. Target HbA1c &lt;7%.</li>")
        narrative_parts.append("<li><strong>Hypertension:</strong> Start lisinopril 10mg daily. Advised on DASH diet, sodium restriction &lt;2400mg/day, regular aerobic exercise.</li>")
        narrative_parts.append("<li><strong>Hyperlipidemia:</strong> Initiate atorvastatin 20mg at bedtime. Dietary counseling for heart-healthy eating.</li>")
        narrative_parts.append("<li><strong>Hypothyroidism:</strong> Begin levothyroxine 25mcg daily, take on empty stomach 30 min before breakfast.</li>")
        narrative_parts.append("<li><strong>Follow-up:</strong> Return in 1 month for medication titration and repeat labs (HbA1c, lipid panel, TSH).</li>")
    elif is_emergency:
        narrative_parts.append("<li><strong>Hypoglycemia Treatment:</strong> Oral glucose administered with symptom resolution. Blood glucose normalized to 108 mg/dL. Discharged home with glucose tablets.</li>")
        narrative_parts.append("<li><strong>Medication Adjustment:</strong> Continue metformin but emphasize importance of regular meals. Consider insulin therapy if oral agents insufficient.</li>")
        narrative_parts.append("<li><strong>Follow-up:</strong> Scheduled with PCP in 2 weeks for diabetes management review and treatment adjustment.</li>")
    elif is_insulin_start:
        narrative_parts.append("<li><strong>Insulin Initiation:</strong> Start insulin glargine 10 units subcutaneous at bedtime. Continue metformin 1000mg BID. Comprehensive injection technique training provided.</li>")
        narrative_parts.append("<li><strong>Glucose Monitoring:</strong> Check fasting glucose daily and 2 hours post-dinner. Call if readings &lt;70 or &gt;250 mg/dL. Target fasting 80-130 mg/dL.</li>")
        narrative_parts.append("<li><strong>Hypoglycemia Prevention:</strong> Reviewed recognition and treatment of low blood sugar. Always carry fast-acting carbohydrate source.</li>")
        narrative_parts.append("<li><strong>Follow-up:</strong> Return in 3 months for A1c check and medication adjustment as needed.</li>")
    elif is_wellness:
        narrative_parts.append("<li><strong>Preventive Care:</strong> Annual diabetic eye exam ordered (fundus photography completed today - no retinopathy). Continue annual foot exams.</li>")
        narrative_parts.append("<li><strong>Cardiovascular Assessment:</strong> Echocardiogram shows preserved ejection fraction 60%. Vascular ultrasound without significant stenosis. Continue current cardiac risk reduction measures.</li>")
        narrative_parts.append("<li><strong>Medications:</strong> Refill metformin 1000mg BID, insulin glargine 10 units qHS, atorvastatin 20mg daily for 90 days.</li>")
        narrative_parts.append("<li><strong>Immunizations:</strong> Influenza and pneumococcal vaccines administered today per CDC guidelines.</li>")
        narrative_parts.append("<li><strong>Follow-up:</strong> Return in 6 months or sooner if concerns arise. Continue quarterly HbA1c monitoring.</li>")
    elif is_followup_adjustment:
        narrative_parts.append("<li><strong>Medication Titration:</strong> Increase metformin to 1000mg BID for improved glycemic control. Patient tolerating without GI side effects.</li>")
        narrative_parts.append("<li><strong>Continue:</strong> Lisinopril 10mg daily, atorvastatin 20mg daily, levothyroxine 25mcg daily.</li>")
        narrative_parts.append("<li><strong>Follow-up:</strong> Return in 6 weeks for repeat HbA1c to assess response to therapy adjustment.</li>")
    else:
        # Generic visit - perform medication reconciliation
        if medications and all_medications:
            # Find medications from previous encounters
            encounter_date = encounter.get('period', {}).get('start', '')
            previous_meds = set()
            current_meds = set()

            for med in medications:
                med_name = med.get('medicationCodeableConcept', {}).get('coding', [{}])[0].get('display', '')
                if med_name:
                    current_meds.add(med_name)

            # Find medications from ALL encounters before this one
            for med in all_medications:
                med_encounter = med.get('encounter', {}).get('reference', '')
                med_name = med.get('medicationCodeableConcept', {}).get('coding', [{}])[0].get('display', '')
                if med_name and med_name not in current_meds:
                    # This is a medication from a previous encounter not in current list
                    previous_meds.add(med_name)

            # Identify changes
            new_meds = current_meds - previous_meds
            continued_meds = current_meds & previous_meds
            discontinued_meds = previous_meds - current_meds

            if new_meds or discontinued_meds or continued_meds:
                narrative_parts.append("<li><strong>Medication Reconciliation:</strong><ul>")

                if new_meds:
                    narrative_parts.append(f"<li><em>New medications:</em> {', '.join(sorted(new_meds))}</li>")

                if discontinued_meds and encounter_index > 0:  # Only show if not first encounter
                    narrative_parts.append(f"<li><em>Discontinued:</em> {', '.join(sorted(list(discontinued_meds)[:3]))}</li>")

                if continued_meds:
                    narrative_parts.append(f"<li><em>Continued:</em> {len(continued_meds)} medications</li>")

                narrative_parts.append("</ul></li>")
            else:
                narrative_parts.append("<li><strong>Medications Continued:</strong> Refills provided for all current medications. {patient_name} reports good adherence and tolerability.</li>")

        elif medications:
            narrative_parts.append(f"<li><strong>Medications Continued:</strong> Refills provided for all current medications. {patient_name} reports good adherence and tolerability.</li>")

        narrative_parts.append("<li><strong>Follow-up:</strong> Continue routine monitoring per chronic disease management protocol.</li>")

    narrative_parts.append("</ol>")

    # Signature line with attestation
    narrative_parts.append("<p><em>This clinical note has been electronically generated and verified by ThetaRho AI-Assisted Clinical Documentation System. The information contained herein is derived from authenticated FHIR resources and clinical data sources.</em></p>")

    return "\n".join(narrative_parts)


def generate_compositions_for_encounters(bundle: Dict[str, Any], practice_id: str, practice_org_id: str = None) -> None:
    """
    Generate enhanced Composition resources for each Encounter with actual clinical data.

    This function creates Composition resources with Assessment and Plan sections that contain
    actual patient clinical data, ensuring the SinceLastVisit query can discover all resources.

    Args:
        bundle: FHIR transaction bundle
        practice_id: Practice identifier
        practice_org_id: Practice Organization ID for extensions
    """
    import html
    from datetime import datetime

    print("\n=== Generating Composition Resources ===")

    # Step 1: Build resource maps for efficient lookup
    encounters = []
    conditions_by_encounter = {}
    observations_by_encounter = {}
    medications_by_encounter = {}
    diagnostic_reports_by_encounter = {}
    all_medications = []  # All medications for reconciliation
    patient_resource = None
    patient_id = None
    practitioner_id = None

    # Extract all resources and build maps
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')
        resource_id = resource.get('id')

        if resource_type == 'Patient':
            patient_id = resource_id
            patient_resource = resource  # Store full patient resource
        elif resource_type == 'Practitioner':
            if practitioner_id is None:  # Take first practitioner
                practitioner_id = resource_id
        elif resource_type == 'Encounter':
            encounters.append(resource)
        elif resource_type == 'Condition':
            encounter_ref = resource.get('encounter', {}).get('reference', '')
            if encounter_ref:
                enc_id = encounter_ref.split('/')[-1]
                if enc_id not in conditions_by_encounter:
                    conditions_by_encounter[enc_id] = []
                conditions_by_encounter[enc_id].append(resource)
        elif resource_type == 'Observation':
            encounter_ref = resource.get('encounter', {}).get('reference', '')
            if encounter_ref:
                enc_id = encounter_ref.split('/')[-1]
                if enc_id not in observations_by_encounter:
                    observations_by_encounter[enc_id] = []
                observations_by_encounter[enc_id].append(resource)
        elif resource_type == 'MedicationRequest':
            all_medications.append(resource)  # Collect all medications for reconciliation
            encounter_ref = resource.get('encounter', {}).get('reference', '')
            if encounter_ref:
                enc_id = encounter_ref.split('/')[-1]
                if enc_id not in medications_by_encounter:
                    medications_by_encounter[enc_id] = []
                medications_by_encounter[enc_id].append(resource)
        elif resource_type == 'DiagnosticReport':
            encounter_ref = resource.get('encounter', {}).get('reference', '')
            if encounter_ref:
                enc_id = encounter_ref.split('/')[-1]
                if enc_id not in diagnostic_reports_by_encounter:
                    diagnostic_reports_by_encounter[enc_id] = []
                diagnostic_reports_by_encounter[enc_id].append(resource)

    print(f"Found {len(encounters)} encounters to process")
    print(f"Patient ID: {patient_id}")
    print(f"Practitioner ID: {practitioner_id}")

    # Sort encounters chronologically by date
    encounters_sorted = sorted(encounters, key=lambda e: e.get('period', {}).get('start', ''))

    # Step 2: Generate Composition for each Encounter
    compositions_created = 0

    for encounter_index, encounter in enumerate(encounters_sorted):
        encounter_id = encounter.get('id')
        encounter_date = encounter.get('period', {}).get('start', '')

        # Extract encounter type for title
        encounter_type = "Clinical Encounter"
        if encounter.get('type'):
            type_coding = encounter['type'][0].get('coding', [])
            if type_coding:
                encounter_type = type_coding[0].get('display', encounter_type)

        # Get related resources for this encounter
        conditions = conditions_by_encounter.get(encounter_id, [])
        observations = observations_by_encounter.get(encounter_id, [])
        medications = medications_by_encounter.get(encounter_id, [])
        diagnostic_reports = diagnostic_reports_by_encounter.get(encounter_id, [])

        # Step 3: Generate context-aware clinical narrative using enhanced template system
        narrative_html = generate_clinical_narrative_for_encounter(
            encounter, conditions, observations, medications, diagnostic_reports, encounter_type,
            patient_resource=patient_resource,
            all_medications=all_medications,
            encounter_index=encounter_index
        )

        # Wrap in XHTML div
        full_narrative = f'<div xmlns="http://www.w3.org/1999/xhtml">\n{narrative_html}\n</div>'

        # Step 4: Create Composition resource
        composition_id = f"comp-{encounter_id}"

        composition = {
            "resourceType": "Composition",
            "id": composition_id,
            "meta": {
                "tag": [
                    {
                        "system": "http://thetarho.ai/fhir/sourcesystem",
                        "code": practice_id,
                        "display": "Mock Patient - Synthea Generated"
                    }
                ]
            },
            "status": "final",
            "type": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "34133-9",
                        "display": "Summary of episode note"
                    }
                ]
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "encounter": {
                "reference": f"Encounter/{encounter_id}"
            },
            "date": encounter_date,
            "title": f"Clinical Note - {encounter_type}",
            "section": [
                {
                    "title": "Assessment/Plan",
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "51847-2",
                                "display": "Assessment/Plan"
                            }
                        ]
                    },
                    "text": {
                        "status": "generated",
                        "div": full_narrative
                    }
                }
            ]
        }

        # Add author if practitioner exists
        if practitioner_id:
            composition["author"] = [
                {
                    "reference": f"Practitioner/{practitioner_id}"
                }
            ]

        # Add to bundle
        bundle['entry'].append({
            "fullUrl": f"Composition/{composition_id}",
            "resource": composition,
            "request": {
                "method": "PUT",
                "url": f"Composition/{composition_id}"
            }
        })

        compositions_created += 1
        print(f"Created Composition for Encounter {encounter_id}: {len(conditions)} conditions, {len(observations)} observations, {len(medications)} medications, {len(diagnostic_reports)} reports")

    print(f"\n✅ Generated {compositions_created} Composition resources with Assessment/Plan sections")
    print("✅ All Compositions have section.title containing 'Assessment' for proper discovery\n")


def remove_empty_encounters(bundle: Dict[str, Any]) -> None:
    """
    Remove routine wellness/checkup encounters that are not clinically significant.

    This removes encounters of the following types:
    - "Well child visit (procedure)" - routine pediatric wellness visits
    - "General examination of patient (procedure)" - routine general checkups

    These encounter types typically contain minimal clinical value (just Composition notes
    and sometimes Immunizations) and clutter the patient timeline. We remove ALL of them
    to keep only clinically significant encounters like:
    - "Encounter for problem (procedure)"
    - "Encounter for check up (procedure)"
    - "Emergency room admission (procedure)"
    - "Administration of vaccine to produce active immunity (procedure)"

    Also removes any resources that ONLY reference the removed encounters.

    Args:
        bundle: FHIR bundle containing Encounter and other resources
    """
    print("\n" + "=" * 100)
    print("REMOVING ROUTINE WELLNESS/CHECKUP ENCOUNTERS")
    print("=" * 100)

    # Define encounter types to remove
    REMOVE_ENCOUNTER_TYPES = [
        "Well child visit (procedure)",
        "General examination of patient (procedure)"
    ]

    # Build map of all encounters
    encounter_map = {}
    encounters_to_remove = []

    # First pass: identify encounters to remove by type
    for entry in bundle['entry']:
        resource = entry['resource']
        if resource.get('resourceType') == 'Encounter':
            enc_id = resource['id']
            enc_type = resource.get('type', [{}])[0].get('text', 'Unknown')
            enc_date = resource.get('period', {}).get('start', '')

            encounter_map[enc_id] = {
                'type': enc_type,
                'date': enc_date,
                'should_remove': enc_type in REMOVE_ENCOUNTER_TYPES
            }

            if enc_type in REMOVE_ENCOUNTER_TYPES:
                encounters_to_remove.append(enc_id)

    total_encounters = len(encounter_map)
    removed_encounter_count = len(encounters_to_remove)
    kept_encounter_count = total_encounters - removed_encounter_count

    print(f"\nTotal Encounters: {total_encounters}")
    print(f"Encounters to Remove: {removed_encounter_count}")
    print(f"Encounters to Keep: {kept_encounter_count}")

    if removed_encounter_count == 0:
        print("\n✅ No routine wellness/checkup encounters found - keeping all encounters")
        return

    # Build map of resources by encounter reference
    resource_encounter_map = {}  # resource_id -> list of encounter_ids

    for entry in bundle['entry']:
        resource = entry['resource']
        resource_type = resource.get('resourceType')
        resource_id = resource.get('id')

        if resource_type == 'Encounter':
            continue

        # Extract encounter references
        encounter_refs = []

        if resource_type in ['Observation', 'DiagnosticReport', 'MedicationRequest',
                            'Condition', 'Procedure', 'Immunization', 'Composition']:
            enc_ref = resource.get('encounter', {}).get('reference', '')
            if enc_ref:
                encounter_refs.append(enc_ref.replace('Encounter/', ''))
        elif resource_type == 'DocumentReference':
            encounters = resource.get('context', {}).get('encounter', [])
            for enc_dict in encounters:
                enc_ref = enc_dict.get('reference', '')
                if enc_ref:
                    encounter_refs.append(enc_ref.replace('Encounter/', ''))
        elif resource_type == 'MedicationAdministration':
            enc_ref = resource.get('context', {}).get('reference', '')
            if enc_ref:
                encounter_refs.append(enc_ref.replace('Encounter/', ''))
        elif resource_type == 'CarePlan':
            encounters = resource.get('encounter', {})
            if isinstance(encounters, dict):
                enc_ref = encounters.get('reference', '')
                if enc_ref:
                    encounter_refs.append(enc_ref.replace('Encounter/', ''))
        elif resource_type == 'Claim':
            # Claim.item[].encounter[] - array of encounters
            items = resource.get('item', [])
            for item in items:
                item_encounters = item.get('encounter', [])
                for enc_dict in item_encounters:
                    enc_ref = enc_dict.get('reference', '')
                    if enc_ref:
                        encounter_refs.append(enc_ref.replace('Encounter/', ''))
        elif resource_type == 'ExplanationOfBenefit':
            # ExplanationOfBenefit.item[].encounter[] - array of encounters
            items = resource.get('item', [])
            for item in items:
                item_encounters = item.get('encounter', [])
                for enc_dict in item_encounters:
                    enc_ref = enc_dict.get('reference', '')
                    if enc_ref:
                        encounter_refs.append(enc_ref.replace('Encounter/', ''))

        if encounter_refs:
            resource_encounter_map[f"{resource_type}/{resource_id}"] = encounter_refs

    # Identify resources that ONLY reference encounters being removed
    resources_to_remove = []

    for resource_key, enc_refs in resource_encounter_map.items():
        # Check if ALL encounter references are to encounters being removed
        all_encounters_removed = all(enc_id in encounters_to_remove for enc_id in enc_refs)

        if all_encounters_removed:
            resources_to_remove.append(resource_key)

    print(f"\nResources ONLY linked to removed encounters: {len(resources_to_remove)}")

    # Remove encounters and orphaned resources
    entries_to_keep = []
    removed_encounter_ids = set(encounters_to_remove)
    removed_resource_keys = set(resources_to_remove)

    encounter_removal_log = {}  # type -> count
    resource_removal_log = {}  # type -> count

    for entry in bundle['entry']:
        resource = entry['resource']
        resource_type = resource.get('resourceType')
        resource_id = resource.get('id')
        resource_key = f"{resource_type}/{resource_id}"

        should_remove = False

        # Remove encounters by ID
        if resource_type == 'Encounter' and resource_id in removed_encounter_ids:
            should_remove = True
            enc_type = encounter_map[resource_id]['type']
            encounter_removal_log[enc_type] = encounter_removal_log.get(enc_type, 0) + 1

        # Remove resources that only reference removed encounters
        elif resource_key in removed_resource_keys:
            should_remove = True
            resource_removal_log[resource_type] = resource_removal_log.get(resource_type, 0) + 1

        if not should_remove:
            entries_to_keep.append(entry)

    bundle['entry'] = entries_to_keep

    print("\n🗑️  Removed Encounters by Type:")
    for enc_type, count in sorted(encounter_removal_log.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {enc_type}: {count}")

    if resource_removal_log:
        print("\n🗑️  Removed Orphaned Resources by Type:")
        for res_type, count in sorted(resource_removal_log.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {res_type}: {count}")

    print(f"\n✅ Removed {removed_encounter_count} routine wellness/checkup encounters")
    print(f"✅ Removed {len(resources_to_remove)} orphaned resources")
    print(f"✅ Kept {kept_encounter_count} clinically significant encounters")


def generate_encounter_summaries(bundle: Dict[str, Any]) -> None:
    """
    Generate dynamic clinical summaries for Encounter resources based on linked resources.

    This function analyzes all resources linked to each encounter and generates a comprehensive
    summary in the Encounter.text.div field. The summary includes:
    - Diagnoses/Conditions
    - Medications prescribed
    - Lab results
    - Imaging studies
    - Procedures performed
    - Immunizations administered

    Only encounters with linked resources get summaries (empty encounters are skipped).

    Args:
        bundle: FHIR bundle containing Encounter and related resources
    """
    print("\n" + "=" * 100)
    print("GENERATING DYNAMIC ENCOUNTER SUMMARIES")
    print("=" * 100)

    # Build resource maps by encounter
    encounter_resources = {}
    all_resources = {}

    # First pass: index all resources by ID
    for entry in bundle['entry']:
        resource = entry['resource']
        resource_id = resource.get('id')
        resource_type = resource.get('resourceType')

        if resource_type == 'Encounter':
            encounter_resources[resource_id] = {
                'encounter': resource,
                'conditions': [],
                'medications': [],
                'observations': [],
                'diagnostic_reports': [],
                'procedures': [],
                'immunizations': [],
                'notes': []
            }

        all_resources[f"{resource_type}/{resource_id}"] = resource

    # Second pass: link resources to encounters
    for entry in bundle['entry']:
        resource = entry['resource']
        resource_type = resource.get('resourceType')
        resource_id = resource.get('id')

        if resource_type == 'Encounter':
            continue

        # Extract encounter reference
        encounter_ref = None

        if resource_type == 'Observation':
            encounter_ref = resource.get('encounter', {}).get('reference', '')
        elif resource_type == 'DiagnosticReport':
            encounter_ref = resource.get('encounter', {}).get('reference', '')
        elif resource_type == 'MedicationRequest':
            encounter_ref = resource.get('encounter', {}).get('reference', '')
        elif resource_type == 'Condition':
            encounter_ref = resource.get('encounter', {}).get('reference', '')
        elif resource_type == 'Procedure':
            encounter_ref = resource.get('encounter', {}).get('reference', '')
        elif resource_type == 'Immunization':
            encounter_ref = resource.get('encounter', {}).get('reference', '')
        elif resource_type in ['DocumentReference', 'Composition']:
            if resource_type == 'DocumentReference':
                encounters = resource.get('context', {}).get('encounter', [])
                if encounters:
                    encounter_ref = encounters[0].get('reference', '')
            else:  # Composition
                encounter_ref = resource.get('encounter', {}).get('reference', '')

        # Add to encounter's resource list
        if encounter_ref:
            enc_id = encounter_ref.replace('Encounter/', '')
            if enc_id in encounter_resources:
                if resource_type == 'Condition':
                    encounter_resources[enc_id]['conditions'].append(resource)
                elif resource_type == 'MedicationRequest':
                    encounter_resources[enc_id]['medications'].append(resource)
                elif resource_type == 'Observation':
                    encounter_resources[enc_id]['observations'].append(resource)
                elif resource_type == 'DiagnosticReport':
                    encounter_resources[enc_id]['diagnostic_reports'].append(resource)
                elif resource_type == 'Procedure':
                    encounter_resources[enc_id]['procedures'].append(resource)
                elif resource_type == 'Immunization':
                    encounter_resources[enc_id]['immunizations'].append(resource)
                elif resource_type in ['DocumentReference', 'Composition']:
                    encounter_resources[enc_id]['notes'].append(resource)

    # Generate summaries
    summaries_generated = 0
    empty_encounters_skipped = 0

    for enc_id, enc_data in encounter_resources.items():
        encounter = enc_data['encounter']

        # Check if encounter has any linked resources
        total_resources = (len(enc_data['conditions']) + len(enc_data['medications']) +
                          len(enc_data['observations']) + len(enc_data['diagnostic_reports']) +
                          len(enc_data['procedures']) + len(enc_data['immunizations']) +
                          len(enc_data['notes']))

        if total_resources == 0:
            empty_encounters_skipped += 1
            continue

        # Build HTML summary
        encounter_type = encounter.get('type', [{}])[0].get('text', 'Encounter')
        encounter_date = encounter.get('period', {}).get('start', 'Unknown date')

        summary_html = f"<div xmlns='http://www.w3.org/1999/xhtml'>"
        summary_html += f"<h3>{encounter_type}</h3>"
        summary_html += f"<p><b>Date:</b> {encounter_date}</p>"

        # Add conditions
        if enc_data['conditions']:
            summary_html += "<h4>Diagnoses/Conditions</h4><ul>"
            for condition in enc_data['conditions']:
                code_text = condition.get('code', {}).get('text', 'Unknown condition')
                clinical_status = condition.get('clinicalStatus', {}).get('coding', [{}])[0].get('code', 'unknown')
                summary_html += f"<li>{code_text} (Status: {clinical_status})</li>"
            summary_html += "</ul>"

        # Add medications
        if enc_data['medications']:
            summary_html += "<h4>Medications Prescribed</h4><ul>"
            for med_req in enc_data['medications']:
                med_display = med_req.get('medicationReference', {}).get('display', 'Unknown medication')
                status = med_req.get('status', 'unknown')
                summary_html += f"<li>{med_display} (Status: {status})</li>"
            summary_html += "</ul>"

        # Add diagnostic reports (labs and imaging)
        if enc_data['diagnostic_reports']:
            lab_reports = []
            imaging_reports = []

            for dr in enc_data['diagnostic_reports']:
                category = dr.get('category', [{}])[0].get('coding', [{}])[0].get('code', '')
                if category == 'LAB':
                    lab_reports.append(dr)
                elif category == 'IMG':
                    imaging_reports.append(dr)
                else:
                    lab_reports.append(dr)  # Default to lab

            if lab_reports:
                summary_html += "<h4>Laboratory Results</h4><ul>"
                for dr in lab_reports:
                    code_text = dr.get('code', {}).get('coding', [{}])[0].get('display', 'Unknown test')
                    result_count = len(dr.get('result', []))
                    summary_html += f"<li>{code_text} ({result_count} results)</li>"
                summary_html += "</ul>"

            if imaging_reports:
                summary_html += "<h4>Imaging Studies</h4><ul>"
                for dr in imaging_reports:
                    code_text = dr.get('code', {}).get('coding', [{}])[0].get('display', 'Unknown imaging')
                    summary_html += f"<li>{code_text}</li>"
                summary_html += "</ul>"

        # Add procedures
        if enc_data['procedures']:
            summary_html += "<h4>Procedures Performed</h4><ul>"
            for proc in enc_data['procedures']:
                code_text = proc.get('code', {}).get('text', 'Unknown procedure')
                status = proc.get('status', 'unknown')
                summary_html += f"<li>{code_text} (Status: {status})</li>"
            summary_html += "</ul>"

        # Add immunizations
        if enc_data['immunizations']:
            summary_html += "<h4>Immunizations Administered</h4><ul>"
            for imm in enc_data['immunizations']:
                vaccine_text = imm.get('vaccineCode', {}).get('text', 'Unknown vaccine')
                summary_html += f"<li>{vaccine_text}</li>"
            summary_html += "</ul>"

        # Add note count
        if enc_data['notes']:
            summary_html += f"<p><b>Clinical Notes:</b> {len(enc_data['notes'])} document(s)</p>"

        summary_html += "</div>"

        # Add text field to encounter
        encounter['text'] = {
            'status': 'generated',
            'div': summary_html
        }

        summaries_generated += 1

        # Debug output for first few
        if summaries_generated <= 3:
            print(f"\n✅ Generated summary for Encounter/{enc_id}:")
            print(f"  Type: {encounter_type}")
            print(f"  Date: {encounter_date}")
            print(f"  Resources: {total_resources} linked items")
            print(f"    - Conditions: {len(enc_data['conditions'])}")
            print(f"    - Medications: {len(enc_data['medications'])}")
            print(f"    - Lab/Imaging: {len(enc_data['diagnostic_reports'])}")
            print(f"    - Procedures: {len(enc_data['procedures'])}")
            print(f"    - Immunizations: {len(enc_data['immunizations'])}")
            print(f"    - Notes: {len(enc_data['notes'])}")

    print(f"\n✅ Generated {summaries_generated} encounter summaries")
    print(f"⏭️  Skipped {empty_encounters_skipped} empty encounters (no summary needed)")


def generate_placeholder_image(modality: str, title: str, width: int = 512, height: int = 512) -> str:
    """
    Generate a placeholder medical image based on modality type.

    Args:
        modality: DICOM modality code (DX, CT, MR, US, XC)
        title: Image title/description
        width: Image width in pixels
        height: Image height in pixels

    Returns:
        Base64-encoded PNG image data
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        import base64
        import random
        import numpy as np
    except ImportError:
        print("⚠️  PIL/Pillow not installed. Install with: pip install Pillow numpy")
        # Return minimal 1x1 placeholder
        import base64
        return base64.b64encode(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89').decode('utf-8')

    # Create base grayscale image
    img_array = np.zeros((height, width), dtype=np.uint8)

    # Modality-specific image generation
    if modality == 'DX':  # Digital Radiography (X-Ray)
        # Create chest X-ray-like image
        # Add vertical gradient (darker at top, lighter at bottom)
        for y in range(height):
            img_array[y, :] = int(50 + (y / height) * 100)

        # Add Gaussian noise for texture
        noise = np.random.normal(0, 10, (height, width))
        img_array = np.clip(img_array + noise, 0, 255).astype(np.uint8)

        # Add simulated lung fields (darker ovals)
        center_left = (width // 3, height // 2)
        center_right = (2 * width // 3, height // 2)
        for y in range(height):
            for x in range(width):
                # Left lung
                if ((x - center_left[0])**2 / 10000 + (y - center_left[1])**2 / 15000) < 1:
                    img_array[y, x] = max(0, img_array[y, x] - 30)
                # Right lung
                if ((x - center_right[0])**2 / 10000 + (y - center_right[1])**2 / 15000) < 1:
                    img_array[y, x] = max(0, img_array[y, x] - 30)

        # Spine (brighter vertical line)
        spine_x = width // 2
        for y in range(height // 3, height):
            for x in range(spine_x - 3, spine_x + 3):
                if 0 <= x < width:
                    img_array[y, x] = min(255, img_array[y, x] + 40)

    elif modality == 'US':  # Ultrasound
        # Create ultrasound-like image with speckle noise
        img_array = np.random.gamma(2.0, 50, (height, width)).astype(np.uint8)

        # Add darker anechoic region (simulated vessel/chamber)
        y_center, x_center = height // 2, width // 2
        for y in range(height):
            for x in range(width):
                if ((x - x_center)**2 / 20000 + (y - y_center)**2 / 5000) < 1:
                    img_array[y, x] = max(0, img_array[y, x] - 80)

        # Add some hyperechoic spots (bright spots)
        for _ in range(20):
            x, y = random.randint(0, width-1), random.randint(0, height-1)
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if 0 <= y+dy < height and 0 <= x+dx < width:
                        img_array[y+dy, x+dx] = min(255, img_array[y+dy, x+dx] + 100)

    elif modality == 'XC':  # External-camera Photography (Fundus)
        # Create retinal fundus-like image with circular field
        img_array = np.ones((height, width), dtype=np.uint8) * 180  # Orangish background

        # Create circular field of view
        center = (width // 2, height // 2)
        radius = min(width, height) // 2 - 20
        for y in range(height):
            for x in range(width):
                dist = np.sqrt((x - center[0])**2 + (y - center[1])**2)
                if dist > radius:
                    img_array[y, x] = 0  # Black outside circle
                else:
                    # Add some variation inside
                    img_array[y, x] = int(160 + random.randint(-20, 20))

        # Add optic disc (bright circle)
        disc_center = (width // 2 - 50, height // 2)
        for y in range(height):
            for x in range(width):
                dist = np.sqrt((x - disc_center[0])**2 + (y - disc_center[1])**2)
                if dist < 30:
                    img_array[y, x] = min(255, img_array[y, x] + 60)

        # Add some vessel-like dark lines
        for i in range(5):
            x1 = disc_center[0] + random.randint(-10, 10)
            y1 = disc_center[1] + random.randint(-10, 10)
            angle = random.uniform(0, 2 * np.pi)
            for dist in range(0, 150, 2):
                x = int(x1 + dist * np.cos(angle))
                y = int(y1 + dist * np.sin(angle))
                if 0 <= x < width and 0 <= y < height:
                    for dx in range(-1, 2):
                        for dy in range(-1, 2):
                            if 0 <= x+dx < width and 0 <= y+dy < height:
                                img_array[y+dy, x+dx] = max(0, img_array[y+dy, x+dx] - 40)

    else:  # Default: simple gradient
        for y in range(height):
            img_array[y, :] = int(128 + (y / height) * 50)
        noise = np.random.normal(0, 15, (height, width))
        img_array = np.clip(img_array + noise, 0, 255).astype(np.uint8)

    # Convert numpy array to PIL Image
    img = Image.fromarray(img_array, mode='L')

    # Add text overlay
    draw = ImageDraw.Draw(img)

    try:
        # Try to load a system font
        font_large = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    except:
        # Fallback to default font
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Add modality indicator
    draw.text((20, 20), f"Modality: {modality}", fill=255, font=font_large)

    # Add title
    title_words = title.split()
    if len(title_words) > 6:
        # Split into multiple lines if too long
        line1 = ' '.join(title_words[:6])
        line2 = ' '.join(title_words[6:])
        draw.text((20, 55), line1, fill=255, font=font_small)
        draw.text((20, 80), line2, fill=255, font=font_small)
    else:
        draw.text((20, 55), title, fill=255, font=font_small)

    # Add watermark
    draw.text((20, height - 40), "SYNTHETIC TEST IMAGE", fill=200, font=font_small)
    draw.text((20, height - 20), "ThetaRho Golden Patient", fill=200, font=font_small)

    # Convert to base64 PNG
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return image_base64


def generate_binary_resources_for_imaging_studies(bundle: Dict[str, Any], practice_id: str,
                                                   practice_org_id: str = None,
                                                   chart_sharing_org_id: str = None) -> None:
    """
    Generate Binary resources with placeholder images for all ImagingStudy instances.

    For each ImagingStudy resource:
    1. Identify modality (DX, CT, MR, US, XC)
    2. Generate appropriate placeholder image
    3. Create Binary resource with base64-encoded PNG
    4. Update ImagingStudy.series.instance.url to reference Binary

    Args:
        bundle: FHIR bundle dictionary
        practice_id: Practice ID for extensions
        practice_org_id: Practice Organization ID
        chart_sharing_org_id: Chart sharing Organization ID
    """
    print("\n" + "=" * 100)
    print("GENERATING BINARY RESOURCES FOR IMAGING STUDIES")
    print("=" * 100)

    binary_entries = []
    binary_id_counter = ID_RANGES['Binary'][0]
    total_instances = 0

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})

        if resource.get('resourceType') != 'ImagingStudy':
            continue

        imaging_study_id = resource.get('id')
        print(f"\nProcessing ImagingStudy/{imaging_study_id}")

        for series_idx, series in enumerate(resource.get('series', [])):
            modality_obj = series.get('modality', {})
            modality_code = modality_obj.get('code', 'DX')
            modality_display = modality_obj.get('display', 'Unknown Modality')

            print(f"  Series {series_idx + 1}: {modality_display} ({modality_code})")

            for instance_idx, instance in enumerate(series.get('instance', [])):
                title = instance.get('title', 'Medical Image')
                instance_uid = instance.get('uid', f"unknown-{instance_idx}")

                # Generate placeholder image
                try:
                    image_base64 = generate_placeholder_image(
                        modality=modality_code,
                        title=title,
                        width=512,
                        height=512
                    )
                except Exception as e:
                    print(f"    ⚠️  Error generating image for '{title}': {e}")
                    continue

                # Create Binary resource
                binary_id = f"{ID_PREFIXES['Binary']}{binary_id_counter}"
                binary_id_counter += 1

                binary_resource = {
                    'resourceType': 'Binary',
                    'id': binary_id,
                    'contentType': 'image/png',
                    'data': image_base64,
                    'meta': {
                        'tag': [{
                            'system': 'http://thetarho.io/fhir/image-source',
                            'code': 'synthetic-placeholder',
                            'display': f'Synthea placeholder image for {modality_display}'
                        }]
                    }
                }

                # Add athenaHealth extensions and metadata
                add_athena_extensions(binary_resource, 'Binary', binary_id, practice_id,
                                      practice_org_id, chart_sharing_org_id)
                add_metadata(binary_resource)
                add_identifiers(binary_resource, 'Binary', binary_id, practice_id)

                # Add to bundle
                binary_entries.append({
                    'fullUrl': f"Binary/{binary_id}",
                    'resource': binary_resource,
                    'request': {
                        'method': 'POST',
                        'url': 'Binary'
                    }
                })

                # Update ImagingStudy instance to reference Binary
                instance['url'] = f"Binary/{binary_id}"

                total_instances += 1
                print(f"    ✓ Instance {instance_idx + 1}: '{title}' → Binary/{binary_id}")

    # Add all Binary resources to bundle
    bundle['entry'].extend(binary_entries)

    # Calculate size estimate
    if total_instances > 0:
        # Each 512x512 PNG is roughly 100-150KB base64-encoded
        size_estimate_mb = (total_instances * 125) / 1024
        print(f"\n" + "=" * 100)
        print(f"✅ Generated {len(binary_entries)} Binary resources for {total_instances} imaging instances")
        print(f"📊 Estimated bundle size increase: ~{size_estimate_mb:.1f} MB")
        print("=" * 100 + "\n")
    else:
        print("\nℹ️  No ImagingStudy resources found - no Binary resources generated\n")


def add_image_urls_to_diagnostic_reports(bundle: Dict[str, Any]) -> None:
    """
    Add imageUrls extension to imaging DiagnosticReports with data URIs for base64 images.

    This function:
    1. Finds all imaging DiagnosticReports (with image_type:IMG tag)
    2. Finds their referenced ImagingStudy resources
    3. Collects Binary resource URLs from ImagingStudy instances
    4. Adds imageUrls extension to DiagnosticReport with data URI format

    The data URI format (data:image/png;base64,{base64}) allows frontend to render
    images directly without fetching from external URLs.
    """
    print("\nAdding imageUrls extensions to imaging DiagnosticReports...")

    # Build mapping of Binary ID -> base64 data
    binary_data_map = {}
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') == 'Binary':
            binary_id = resource.get('id')
            binary_data = resource.get('data', '')
            if binary_id and binary_data:
                binary_data_map[binary_id] = binary_data

    print(f"  Found {len(binary_data_map)} Binary resources with image data")

    # Build mapping of ImagingStudy ID -> list of Binary IDs
    imaging_study_to_binaries = {}
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') == 'ImagingStudy':
            imaging_id = resource.get('id')
            binary_ids = []

            # Collect Binary references from all series instances
            for series in resource.get('series', []):
                for instance in series.get('instance', []):
                    url = instance.get('url', '')
                    # URL format is "Binary/{id}"
                    if url.startswith('Binary/'):
                        binary_id = url.split('/')[-1]
                        binary_ids.append(binary_id)

            if imaging_id and binary_ids:
                imaging_study_to_binaries[imaging_id] = binary_ids

    print(f"  Found {len(imaging_study_to_binaries)} ImagingStudy resources with Binary references")

    # Add imageUrls extension to DiagnosticReports
    updated_count = 0
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') != 'DiagnosticReport':
            continue

        # Check if this is an imaging DR
        tags = resource.get('meta', {}).get('tag', [])
        is_imaging = any(tag.get('code') == 'image_type:IMG' for tag in tags)
        if not is_imaging:
            continue

        # Get referenced ImagingStudy
        imaging_study_refs = resource.get('imagingStudy', [])
        if not imaging_study_refs:
            continue

        # Collect all Binary data URIs for this DiagnosticReport
        data_uris = []
        for imaging_ref in imaging_study_refs:
            imaging_id = imaging_ref.get('reference', '').split('/')[-1]
            binary_ids = imaging_study_to_binaries.get(imaging_id, [])

            for binary_id in binary_ids:
                base64_data = binary_data_map.get(binary_id)
                if base64_data:
                    # Create data URI
                    data_uri = f"data:image/png;base64,{base64_data}"
                    data_uris.append(data_uri)

        if data_uris:
            # Add or update imageUrls extension
            if 'extension' not in resource:
                resource['extension'] = []

            # Remove existing imageUrls extension if present
            resource['extension'] = [ext for ext in resource['extension'] if ext.get('url') != 'imageUrls']

            # Add new imageUrls extension with semicolon-separated data URIs
            resource['extension'].append({
                'url': 'imageUrls',
                'valueString': ';'.join(data_uris)
            })

            updated_count += 1
            dr_id = resource.get('id')
            print(f"  ✓ DiagnosticReport/{dr_id}: Added {len(data_uris)} image data URI(s)")

    print(f"\n✅ Added imageUrls to {updated_count} imaging DiagnosticReport resources\n")


def convert_to_athena_format(
    input_file: str,
    output_file: str,
    patient_id: int,
    practice_id: str,
    virtual_dates: List[str] = None
) -> None:
    """
    Main conversion function.

    Args:
        input_file: Path to Synthea FHIR bundle (UUID-based)
        output_file: Path for athenaHealth-formatted output
        patient_id: Base patient ID (e.g., 995000)
        practice_id: Practice identifier (e.g., "a-16349")
        virtual_dates: List of dates for virtual encounters
    """
    print(f"\n{'='*70}")
    print(f"Converting Synthea FHIR Bundle to AthenaHealth Format")
    print(f"{'='*70}")
    print(f"Input:  {input_file}")
    print(f"Output: {output_file}")
    print(f"Patient ID: {patient_id}")
    print(f"Practice ID: {practice_id}")

    # Load main bundle
    print("\nLoading FHIR bundle...")
    with open(input_file, 'r') as f:
        bundle = json.load(f)

    # Load additional bundles (Practitioner, Organization, Location)
    print("\nLoading additional resource bundles...")
    additional_bundles = load_additional_bundles(input_file)

    # Merge all bundles
    if additional_bundles:
        print(f"\nMerging {len(additional_bundles)} additional bundles...")
        bundle = merge_bundles(bundle, additional_bundles)

    entry_count = len(bundle.get('entry', []))
    print(f"Total bundle entries: {entry_count}")

    # Step 1: Build UUID mapping
    uuid_map = build_uuid_mapping(bundle, patient_id)

    # Step 2: Convert all IDs
    convert_all_ids(bundle, uuid_map)

    # Step 3: Update all references
    update_all_references(bundle, uuid_map)

    # Step 4: Find Organization IDs for extensions
    print("\nFinding Organization IDs for extensions...")
    org_ids = []
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') == 'Organization':
            org_ids.append(resource.get('id'))

    practice_org_id = org_ids[0] if org_ids else "800001"
    chart_sharing_org_id = practice_org_id  # Use same org for chart-sharing
    print(f"  Practice Organization ID: {practice_org_id}")
    print(f"  Chart Sharing Organization ID: {chart_sharing_org_id}")

    # Step 5: Add athena metadata to all resources
    print("\nAdding athenaHealth metadata...")
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')
        resource_id = resource.get('id')

        if resource_type and resource_id:
            add_athena_extensions(resource, resource_type, resource_id, practice_id,
                                practice_org_id, chart_sharing_org_id)
            add_metadata(resource)
            add_identifiers(resource, resource_type, resource_id, practice_id)

    # Step 6: Mark virtual encounters
    if virtual_dates:
        mark_virtual_encounters(bundle, virtual_dates)

    # Step 7: Add pharmacy notes
    add_pharmacy_notes(bundle)

    # Step 8: Fix CodeableConcept text fields for ThetaRho service compatibility
    fix_codeable_concept_text_fields(bundle)

    # Step 9: Convert MedicationRequest medication field to Reference with display
    # Pass practice_id and practice_org_id for proper Medication resource creation
    # RE-ENABLED: FhirDataValidationQueryService.java:583 requires Reference type with display field
    convert_medication_codeable_concept_to_reference(bundle, practice_id, practice_org_id)

    # Step 9b: Enhance MedicationRequests with dosage text and start/end dates
    enhance_medication_requests_with_dosage_and_dates(bundle)

    # Step 9c: Generate observations for DiagnosticReport panels (CBC, CMP, Lipid, BMP, HbA1c)
    generate_observations_for_diagnostic_reports(bundle)

    # Step 9d: Link Observations to DiagnosticReports by populating result[] arrays
    link_observations_to_diagnostic_reports(bundle)

    # Step 9e: Add text field to Condition category for backend compatibility
    add_category_text_to_conditions(bundle)

    # Step 10: Add DiagnosticReport dr_subtype tags
    add_diagnostic_report_subtypes(bundle)

    # Step 10a: Remove clinical documentation DiagnosticReports (H&P notes, consult notes, etc.)
    # These should only exist as Composition resources, not DiagnosticReports
    print("\nRemoving clinical documentation DiagnosticReports...")
    remove_clinical_documentation_diagnostic_reports(bundle)

    # Step 10b: Generate DiagnosticReport resources for ImagingStudy resources
    generate_diagnostic_reports_for_imaging_studies(bundle, practice_id, practice_org_id, chart_sharing_org_id)

    # Step 11: Add serviceProvider display to Encounters
    add_service_provider_display(bundle)

    # Step 12: Generate Composition resources for each Encounter
    generate_compositions_for_encounters(bundle, practice_id, practice_org_id)

    # Step 12a: Remove empty encounters (keep only first baseline encounter)
    remove_empty_encounters(bundle)

    # Step 12b: Generate dynamic encounter summaries for meaningful encounters
    generate_encounter_summaries(bundle)

    # Step 12c: Generate Binary resources for ImagingStudy instances (placeholder images)
    generate_binary_resources_for_imaging_studies(bundle, practice_id, practice_org_id, chart_sharing_org_id)

    # Step 13: Add generalPractitioner reference to Patient resource
    add_general_practitioner_to_patient(bundle)

    # Step 15: Process CCDA XML with updated IDs (do this before saving to have full uuid_map)
    # Create directory structure compatible with upload_fhir_bundles_to_hapi.sh
    # Structure: mock_patients/bundles/ and mock_patients/t{patient_id}/

    output_dir = os.path.dirname(output_file) if os.path.dirname(output_file) else '.'

    # Determine patient ID with 't' prefix for directory names
    patient_id_str = f"t{patient_id}"

    # Create mock_patients structure
    mock_patients_dir = os.path.join(output_dir, "mock_patients")
    bundles_dir = os.path.join(mock_patients_dir, "bundles")
    patient_dir = os.path.join(mock_patients_dir, patient_id_str)

    # Create directories
    os.makedirs(bundles_dir, exist_ok=True)
    os.makedirs(patient_dir, exist_ok=True)
    print(f"\nCreated directory structure:")
    print(f"  {bundles_dir}")
    print(f"  {patient_dir}")

    process_ccda_xml(input_file, uuid_map, bundles_dir, str(patient_id), practice_id)

    # Step 16: Extract and save shared resources (Organization, Practitioner, Location) to bundles/
    print(f"\nExtracting shared resources (Organization, Practitioner, Location)...")
    save_shared_resources(bundle, bundles_dir)

    # Step 17: Remove shared resources from main bundle (they will be uploaded separately)
    print(f"\nRemoving shared resources from patient bundle...")
    shared_resource_types = ['Organization', 'Practitioner', 'Location', 'PractitionerRole']
    original_count = len(bundle.get('entry', []))

    bundle['entry'] = [
        entry for entry in bundle.get('entry', [])
        if entry.get('resource', {}).get('resourceType') not in shared_resource_types
    ]

    removed_count = original_count - len(bundle['entry'])
    print(f"  ✓ Removed {removed_count} shared resource(s) from patient bundle")
    print(f"  ✓ Patient bundle now contains {len(bundle['entry'])} resources")

    # Step 18: Sort bundle entries by resource dependency order
    # Medication resources must come BEFORE MedicationRequest resources
    # This ensures HAPI FHIR can resolve references when using PUT requests
    print(f"\nSorting bundle entries by dependency order...")

    RESOURCE_ORDER = {
        'Patient': 0,
        'Medication': 1,
        'MedicationRequest': 2,
        'Encounter': 3,
        'Condition': 4,
        'Observation': 5,
        'DiagnosticReport': 6,
        'Procedure': 7,
        'AllergyIntolerance': 8,
        'Immunization': 9,
        'DocumentReference': 10,
        'MedicationAdministration': 11,
        'Claim': 12,
        'ExplanationOfBenefit': 13,
        'Provenance': 14
    }

    def get_sort_key(entry):
        resource_type = entry.get('resource', {}).get('resourceType', 'ZZZ')
        return RESOURCE_ORDER.get(resource_type, 999)

    bundle['entry'] = sorted(bundle['entry'], key=get_sort_key)
    print(f"  ✓ Sorted {len(bundle['entry'])} entries by dependency order")

    # Save patient bundle to bundles directory with naming convention expected by upload script
    # Format: bundles/{PATIENT_ID}_bundle.json
    patient_bundle_path = os.path.join(bundles_dir, f"{patient_id_str}_bundle.json")

    print(f"\nSaving patient bundle (without shared resources) to {patient_bundle_path}...")
    with open(patient_bundle_path, 'w') as f:
        json.dump(bundle, f, indent=2)

    if output_file != patient_bundle_path:
        print(f"Saving copy to user-specified path: {output_file}...")
        with open(output_file, 'w') as f:
            json.dump(bundle, f, indent=2)

    print(f"\n{'='*70}")
    print(f"Conversion complete!")
    print(f"{'='*70}")
    print(f"\nDirectory structure created for upload_fhir_bundles_to_hapi.sh:")
    print(f"  Patient bundle:    {patient_bundle_path}")
    print(f"  Shared resources:  {bundles_dir}/Organization.json")
    print(f"                     {bundles_dir}/Practitioner.json")
    print(f"                     {bundles_dir}/Location.json")
    print(f"                     {bundles_dir}/PractitionerRole.json")
    print(f"  Patient directory: {patient_dir}/")
    print(f"\nNext steps:")
    print(f"1. Upload to HAPI FHIR: ./scripts/upload_fhir_bundles_to_hapi.sh {patient_id_str}")
    print(f"2. Generate clinical notes: python3 chatty.py -b {patient_bundle_path}")
    print(f"3. Split bundle by resource type: python3 scripts/split_bundle_by_resource.py --input {patient_bundle_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Convert Synthea FHIR bundle to athenaHealth numeric string format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic conversion
  python3 convert_to_athena_format.py \\
    --input output/fhir/generated.json \\
    --output output/fhir/athena_995000.json \\
    --patient-id 995000 \\
    --practice-id a-16349

  # With virtual encounter dates
  python3 convert_to_athena_format.py \\
    --input output/fhir/generated.json \\
    --output output/fhir/athena_995000.json \\
    --patient-id 995000 \\
    --practice-id a-16349 \\
    --virtual-dates 2024-01-15 2024-04-08 2025-01-10
        """
    )

    parser.add_argument('--input', required=True, help='Input FHIR bundle (Synthea output)')
    parser.add_argument('--output', required=True, help='Output FHIR bundle (athenaHealth format)')
    parser.add_argument('--patient-id', type=int, default=1000000, help='Base patient ID (default: 1000000)')
    parser.add_argument('--practice-id', default='a-16349', help='Practice ID (default: a-16349)')
    parser.add_argument('--virtual-dates', nargs='*', default=VIRTUAL_ENCOUNTER_DATES,
                        help='Dates for virtual encounters (YYYY-MM-DD)')

    args = parser.parse_args()

    convert_to_athena_format(
        input_file=args.input,
        output_file=args.output,
        patient_id=args.patient_id,
        practice_id=args.practice_id,
        virtual_dates=args.virtual_dates
    )


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
CCDA Addon Generator for ThetaRho Platform
Generates a generic wellness visit CCDA addon for existing patients

This script:
1. Moves ccda_addon module from custom_modules to modules folder
2. Generates CCDA using Synthea (no -m flag, uses modules folder)
3. Parses generated CCDA and filters ONLY addon encounter resources
4. Fetches existing patient data from FHIR server
5. Replaces all UUIDs with alphanumeric test IDs (similar to convert_to_athena_format.py)
6. Updates patient demographics to reference existing patient
7. Updates all encounter dates to specified date
8. Filters CCDA to keep ONLY the addon encounter (removes all patient history)
9. Saves final addon CCDA as {patient_id}_addon.xml

Usage:
    python generate_addon.py --patient-id t1210 --server-url danvers-clone.thetarho.com [--encounter-date 2025-11-13]

Author: ThetaRho AI Team
"""

import argparse
import os
import sys
import shutil
import subprocess
import glob
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import random
import re
import time
import csv

# ============================================================================
# Color Codes for Terminal Output
# ============================================================================
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

# ============================================================================
# Helper Functions for Formatted Output
# ============================================================================
def print_header(message):
    """Print a colored header message"""
    print(f"\n{Colors.CYAN}{'='*80}{Colors.NC}")
    print(f"{Colors.CYAN}{message.center(80)}{Colors.NC}")
    print(f"{Colors.CYAN}{'='*80}{Colors.NC}\n")

def print_step(step_num, message):
    """Print a step number with message"""
    print(f"{Colors.BLUE}[Step {step_num}]{Colors.NC} {message}")

def print_success(message):
    """Print a success message"""
    print(f"{Colors.GREEN}✓ {message}{Colors.NC}")

def print_error(message):
    """Print an error message"""
    print(f"{Colors.RED}✗ ERROR: {message}{Colors.NC}")

def print_warning(message):
    """Print a warning message"""
    print(f"{Colors.YELLOW}⚠ WARNING: {message}{Colors.NC}")

def print_info(message):
    """Print an info message"""
    print(f"{Colors.CYAN}ℹ {message}{Colors.NC}")

# ============================================================================
# ID Generation Configuration (matching convert_to_athena_format.py)
# ============================================================================
ID_RANGES = {
    'Encounter': (10100000, 19999999),
    'Observation': (40000000, 99999999),
    'DiagnosticReport': (100000000, 119999999),
    'MedicationRequest': (120000000, 139999999),
    'Procedure': (140000000, 159999999),
}

ID_PREFIXES = {
    'Encounter': 't',
    'Observation': 't',
    'DiagnosticReport': 't',
    'MedicationRequest': 't',
    'Procedure': 't',
}

# ============================================================================
# Global Variables
# ============================================================================
SYNTHEA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUSTOM_MODULES_DIR = os.path.join(SYNTHEA_DIR, 'src', 'main', 'resources', 'custom_modules')
MODULES_DIR = os.path.join(SYNTHEA_DIR, 'src', 'main', 'resources', 'modules')
OUTPUT_CCDA_DIR = os.path.join(SYNTHEA_DIR, 'output', 'ccda')
MOCK_PATIENTS_DIR = os.path.join(SYNTHEA_DIR, 'mock_patients')
ADDON_MODULE_NAME = 'ccda_addon.json'

# CCDA Section codes that should be in the addon
ADDON_SECTIONS = {
    '48765-2': 'Allergies',  # Empty "no known allergies"
    '10160-0': 'Medications',
    '30954-2': 'Diagnostic Results',
    '46240-8': 'Encounters',
    '8716-3': 'Vital Signs',
    '47519-4': 'Procedures',
}

# LOINC component name mappings (loaded from CSV file)
LOINC_COMPONENT_MAP = {}

def load_loinc_mappings():
    """Load LOINC code to component name mappings from CSV file.

    This mapping ensures CCDA captions match exact strings in the database's titleLoincMap.
    The backend's LoincCodesService.findLoincCode() requires exact string match for successful lookup.

    Returns:
        dict: Mapping of LOINC codes to their component names from trx_loinc_codes table
    """
    global LOINC_COMPONENT_MAP

    # Path to the CSV mapping file (relative to script directory)
    mapping_file = os.path.join(SYNTHEA_DIR, 'loinc_component_mappings.csv')

    if not os.path.exists(mapping_file):
        print_warning(f"LOINC mapping file not found: {mapping_file}")
        print_info("CCDA captions will use original display names (may not match database)")
        return {}

    try:
        with open(mapping_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                loinc_num = row['loinc_num'].strip()
                component = row['component'].strip()
                LOINC_COMPONENT_MAP[loinc_num] = component

        print_success(f"Loaded {len(LOINC_COMPONENT_MAP)} LOINC component mappings")
        return LOINC_COMPONENT_MAP

    except Exception as e:
        print_error(f"Error loading LOINC mappings: {str(e)}")
        return {}

def get_caption_for_loinc(loinc_code, original_display_name):
    """Get the correct caption for a LOINC code to match database titleLoincMap.

    Args:
        loinc_code (str): LOINC code (e.g., '58410-2')
        original_display_name (str): Original display name from CCDA

    Returns:
        str: Component name from database if found, otherwise original display name
    """
    if loinc_code in LOINC_COMPONENT_MAP:
        return LOINC_COMPONENT_MAP[loinc_code]

    # Fallback to original display name if LOINC not in mapping
    return original_display_name

# ============================================================================
# UUID Mapping and Replacement Functions
# ============================================================================

# ID Ranges - MUST match convert_to_athena_format.py exactly
ID_RANGES = {
    'Patient': (10000000, 10000000),
    'Encounter': (10100000, 19999999),
    'Condition': (20000000, 39999999),
    'Observation': (40000000, 99999999),
    'DiagnosticReport': (100000000, 119999999),
    'MedicationRequest': (120000000, 139999999),
    'Procedure': (140000000, 159999999),
    'DocumentReference': (160000000, 179999999),
    'Immunization': (180000000, 189999999),
    'CarePlan': (190000000, 199999999),
    'Goal': (200000000, 209999999),
    'AllergyIntolerance': (210000000, 219999999),
    'Binary': (220000000, 239999999),
    'Media': (240000000, 249999999),
    'ImagingStudy': (250000000, 259999999),
    'Claim': (260000000, 279999999),
    'ExplanationOfBenefit': (280000000, 299999999),
    'Provenance': (300000000, 319999999),
    'Composition': (320000000, 339999999),
}

# ID Prefix - MUST match convert_to_athena_format.py exactly
ID_PREFIX = 't'

# AthenaID Prefixes - MUST match convert_to_athena_format.py exactly
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
    'Medication': 'medication',
    'MedicationAdministration': 'medicationadministration',
    'MedicationStatement': 'medicationstatement',
    'Practitioner': 'practitioner',
    'PractitionerRole': 'practitionerrole',
    'Organization': 'organization',
    'Location': 'location',
}

def detect_resource_type_from_context(xml_content, uuid, uuids_found):
    """
    Detect resource type from XML context around the UUID.
    This heuristic analysis helps assign proper ID ranges.
    """
    # Find the UUID in context
    uuid_pos = xml_content.find(uuid)
    if uuid_pos == -1:
        return 'unknown'

    # Get context around UUID (500 chars before and after)
    context_start = max(0, uuid_pos - 500)
    context_end = min(len(xml_content), uuid_pos + 500)
    context = xml_content[context_start:context_end]

    # Check for resource type indicators in CCDA XML
    # Look for CCDA section codes and entry types
    if 'classCode="ENC"' in context or '46240-8' in context:  # Encounters section
        return 'Encounter'
    elif 'classCode="OBS"' in context and ('8716-3' in context or 'vital' in context.lower()):  # Vitals
        return 'Observation'
    elif 'classCode="OBS"' in context and ('30954-2' in context or 'laboratory' in context.lower()):  # Labs
        return 'Observation'
    elif 'classCode="CLUSTER"' in context and ('58410-2' in context or '24323-8' in context):  # DiagnosticReport
        return 'DiagnosticReport'
    elif 'classCode="SBADM"' in context or '10160-0' in context:  # Medications
        return 'MedicationRequest'
    elif 'classCode="PROC"' in context or '47519-4' in context:  # Procedures
        return 'Procedure'

    # Default to Observation if unclear (most common in CCDA)
    return 'Observation'

def build_uuid_mapping(xml_content, patient_id):
    """
    Build a mapping from UUIDs to new alphanumeric IDs.
    Uses EXACT same logic as convert_to_athena_format.py:
    - High-entropy seed from timestamp, process ID, random salt
    - Resource-type-specific ID ranges
    - Format: t{numeric_id} where numeric_id is from appropriate range
    """
    uuid_map = {}
    process_id = os.getpid()
    timestamp_microseconds = int(time.time() * 1_000_000)
    random_salt = random.randint(0, 999999)

    # Create high-entropy seed - EXACT same logic as convert_to_athena_format.py
    seed_value = hash((patient_id, timestamp_microseconds, process_id, random_salt))
    rng = random.Random(seed_value)

    # Track used IDs globally to avoid collisions
    all_used_ids = set()

    # Find all UUIDs in the XML content
    uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    uuids_found = set(re.findall(uuid_pattern, xml_content, re.IGNORECASE))

    print_info(f"Found {len(uuids_found)} unique UUIDs to replace")

    # Generate new IDs for each UUID using resource-type-specific ranges
    for uuid in uuids_found:
        # Detect resource type from XML context
        resource_type = detect_resource_type_from_context(xml_content, uuid, uuids_found)

        # Get ID range for this resource type
        if resource_type in ID_RANGES:
            start_range, end_range = ID_RANGES[resource_type]
        else:
            # Default to Observation range for unknown types
            start_range, end_range = ID_RANGES['Observation']

        # Generate random ID within range - EXACT same logic as convert_to_athena_format.py
        resource_seed = hash((
            resource_type,
            patient_id,
            timestamp_microseconds,
            process_id,
            random_salt,
            uuid,
            rng.random()
        ))
        resource_rng = random.Random(resource_seed)

        # Generate random offset within the resource type's designated range
        random_offset = resource_rng.randint(0, end_range - start_range)
        candidate_id = start_range + random_offset

        # Handle collisions
        max_attempts = end_range - start_range + 1
        numeric_id = None

        for attempt in range(max_attempts):
            test_id = start_range + ((random_offset + attempt) % (end_range - start_range + 1))

            if test_id not in all_used_ids:
                numeric_id = test_id
                all_used_ids.add(numeric_id)
                break

        if numeric_id is None:
            raise ValueError(f"ID range exhausted for {resource_type}")

        # Add prefix to make ID alphanumeric - EXACT same format as convert_to_athena_format.py
        new_id = f"{ID_PREFIX}{numeric_id}"
        uuid_map[uuid] = new_id

    return uuid_map

def replace_uuids_in_xml(xml_content, uuid_map):
    """
    Replace all UUIDs in the XML content with mapped alphanumeric IDs
    """
    replacements_made = 0

    for uuid, new_id in uuid_map.items():
        count = xml_content.count(uuid)
        if count > 0:
            xml_content = xml_content.replace(uuid, new_id)
            replacements_made += count

    print_success(f"Replaced {replacements_made} UUID references")
    return xml_content

def update_patient_demographics(root, patient_data, practice_data, namespaces):
    """
    Update patient demographic information in CCDA to match existing patient.
    Updates: recordTarget, author, custodian, and document title.
    """
    # Extract patient name for use throughout
    patient_name_data = patient_data.get('name', [{}])[0]
    given_names = patient_name_data.get('given', [])
    family_name = patient_name_data.get('family', '')
    full_name = ' '.join(given_names) + ' ' + family_name
    patient_id = patient_data.get('id', '')

    # ========================================================================
    # 1. Update recordTarget (patient demographics)
    # ========================================================================

    # Update patient ID
    patient_id_elem = root.find('.//hl7:recordTarget//hl7:patientRole//hl7:id[@assigningAuthorityName="https://github.com/synthetichealth/synthea"]', namespaces)
    if patient_id_elem is not None:
        patient_id_elem.set('extension', patient_id)

    # Update patient name
    patient_name_elem = root.find('.//hl7:recordTarget//hl7:patient//hl7:name', namespaces)
    if patient_name_elem is not None:
        # Clear existing name elements
        for child in list(patient_name_elem):
            patient_name_elem.remove(child)

        # Add given name(s)
        for given in given_names:
            given_elem = ET.SubElement(patient_name_elem, '{urn:hl7-org:v3}given')
            given_elem.text = given

        # Add family name
        family_elem = ET.SubElement(patient_name_elem, '{urn:hl7-org:v3}family')
        family_elem.text = family_name

    # Update patient gender
    gender_elem = root.find('.//hl7:recordTarget//hl7:patient//hl7:administrativeGenderCode', namespaces)
    if gender_elem is not None and patient_data.get('gender'):
        gender_code = 'M' if patient_data['gender'] == 'male' else 'F'
        gender_elem.set('code', gender_code)
        gender_elem.set('displayName', patient_data['gender'].capitalize())

    # Update birth date
    birthtime_elem = root.find('.//hl7:recordTarget//hl7:patient//hl7:birthTime', namespaces)
    if birthtime_elem is not None and patient_data.get('birthDate'):
        birth_date = patient_data['birthDate'].replace('-', '')
        existing_value = birthtime_elem.get('value', '')
        if len(existing_value) > 8:
            birthtime_elem.set('value', birth_date + existing_value[8:])
        else:
            birthtime_elem.set('value', birth_date)

    print_info(f"  ✓ Updated recordTarget: {full_name} ({patient_id})")

    # ========================================================================
    # 2. Update author organization (if practice data provided)
    # ========================================================================

    if practice_data:
        practice_name = practice_data.get('name', 'Unknown Practice')

        # Update author/representedOrganization/name
        author_org_name = root.find('.//hl7:author//hl7:representedOrganization//hl7:name', namespaces)
        if author_org_name is not None:
            author_org_name.text = practice_name

        print_info(f"  ✓ Updated author organization: {practice_name}")

    # ========================================================================
    # 3. Update custodian organization
    # ========================================================================

    if practice_data:
        practice_name = practice_data.get('name', 'Unknown Practice')

        # Update custodian/representedCustodianOrganization/name
        custodian_org_name = root.find('.//hl7:custodian//hl7:representedCustodianOrganization//hl7:name', namespaces)
        if custodian_org_name is not None:
            custodian_org_name.text = practice_name

        print_info(f"  ✓ Updated custodian organization: {practice_name}")

    # ========================================================================
    # 4. Update document title
    # ========================================================================

    title_elem = root.find('.//hl7:title', namespaces)
    if title_elem is not None:
        title_elem.text = f"C-CDA R2.1 Patient Record: {full_name}"
        print_info(f"  ✓ Updated document title: {full_name}")

    print_success("Updated patient demographics, author, custodian, and title")
    return root

def update_encounter_dates(root, encounter_date, namespaces):
    """
    Update all encounter and observation dates to the specified date
    ONLY for the addon encounter (Encounter for check up)
    """
    # Convert encounter_date (YYYY-MM-DD) to HL7 format (YYYYMMDDHHMMSS)
    date_obj = datetime.strptime(encounter_date, '%Y-%m-%d')
    hl7_datetime = date_obj.strftime('%Y%m%d%H%M%S')

    dates_updated = 0

    # Find the addon encounter in the Encounters section
    encounters_section = None
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is not None and code_elem.get('code') == '46240-8':  # Encounters section
            encounters_section = section
            break

    if encounters_section is not None:
        # Find the "Encounter for check up" entry
        for entry in encounters_section.findall('.//hl7:entry', namespaces):
            encounter = entry.find('.//hl7:encounter', namespaces)
            if encounter is not None:
                code = encounter.find('.//hl7:code', namespaces)
                if code is not None and code.get('code') == '185349003':  # Encounter for check up
                    # Update this encounter's effective time
                    effective_time = encounter.find('hl7:effectiveTime', namespaces)
                    if effective_time is not None:
                        low = effective_time.find('hl7:low', namespaces)
                        high = effective_time.find('hl7:high', namespaces)
                        if low is not None:
                            low.set('value', hl7_datetime)
                            dates_updated += 1
                        if high is not None:
                            high.set('value', hl7_datetime)
                            dates_updated += 1

    # Update dates in Vital Signs section (only for addon vitals)
    vitals_section = None
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is not None and code_elem.get('code') == '8716-3':  # Vital Signs
            vitals_section = section
            break

    if vitals_section is not None:
        # Update organizer effective time
        for organizer in vitals_section.findall('.//hl7:organizer', namespaces):
            effective_time = organizer.find('hl7:effectiveTime', namespaces)
            if effective_time is not None:
                # Update effectiveTime with direct value attribute
                if 'value' in effective_time.attrib:
                    effective_time.set('value', hl7_datetime)
                    dates_updated += 1
                # Update effectiveTime with low/high child elements
                else:
                    time_low = effective_time.find('hl7:low', namespaces)
                    time_high = effective_time.find('hl7:high', namespaces)
                    if time_low is not None and 'value' in time_low.attrib:
                        time_low.set('value', hl7_datetime)
                        dates_updated += 1
                    if time_high is not None and 'value' in time_high.attrib:
                        time_high.set('value', hl7_datetime)
                        dates_updated += 1

            # Update component observations
            for component in organizer.findall('.//hl7:component', namespaces):
                obs = component.find('hl7:observation', namespaces)
                if obs is not None:
                    effective_time = obs.find('hl7:effectiveTime', namespaces)
                    if effective_time is not None and 'value' in effective_time.attrib:
                        effective_time.set('value', hl7_datetime)
                        dates_updated += 1

    # Update dates in Diagnostic Results section (labs)
    results_section = None
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is not None and code_elem.get('code') == '30954-2':  # Diagnostic Results
            results_section = section
            break

    if results_section is not None:
        for organizer in results_section.findall('.//hl7:organizer', namespaces):
            effective_time = organizer.find('hl7:effectiveTime', namespaces)
            if effective_time is not None:
                # Update effectiveTime with direct value attribute
                if 'value' in effective_time.attrib:
                    effective_time.set('value', hl7_datetime)
                    dates_updated += 1
                # Update effectiveTime with low/high child elements
                else:
                    time_low = effective_time.find('hl7:low', namespaces)
                    time_high = effective_time.find('hl7:high', namespaces)
                    if time_low is not None and 'value' in time_low.attrib:
                        time_low.set('value', hl7_datetime)
                        dates_updated += 1
                    if time_high is not None and 'value' in time_high.attrib:
                        time_high.set('value', hl7_datetime)
                        dates_updated += 1

            # Update component observations
            for component in organizer.findall('.//hl7:component', namespaces):
                obs = component.find('hl7:observation', namespaces)
                if obs is not None:
                    effective_time = obs.find('hl7:effectiveTime', namespaces)
                    if effective_time is not None and 'value' in effective_time.attrib:
                        effective_time.set('value', hl7_datetime)
                        dates_updated += 1

    # Update dates in Medications section
    meds_section = None
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is not None and code_elem.get('code') == '10160-0':  # Medications
            meds_section = section
            break

    if meds_section is not None:
        for subst_admin in meds_section.findall('.//hl7:substanceAdministration', namespaces):
            effective_time = subst_admin.find('hl7:effectiveTime', namespaces)
            if effective_time is not None:
                low = effective_time.find('hl7:low', namespaces)
                if low is not None:
                    low.set('value', hl7_datetime)
                    dates_updated += 1

    # Update dates in Procedures section
    procs_section = None
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is not None and code_elem.get('code') == '47519-4':  # Procedures
            procs_section = section
            break

    if procs_section is not None:
        for procedure in procs_section.findall('.//hl7:procedure', namespaces):
            effective_time = procedure.find('hl7:effectiveTime', namespaces)
            if effective_time is not None and 'value' in effective_time.attrib:
                effective_time.set('value', hl7_datetime)
                dates_updated += 1

    print_success(f"Updated {dates_updated} date/time values to {encounter_date}")
    return root

def filter_narrative_table(section, num_rows_to_keep, namespaces):
    """
    Simple table filtering - keeps last N rows in tbody.
    Used for sections where we don't need to rebuild from structured data.
    """
    text_elem = section.find('hl7:text', namespaces)
    if text_elem is None:
        return

    # Find table (not in namespace)
    table = None
    for child in text_elem:
        if child.tag == 'table' or child.tag.endswith('}table'):
            table = child
            break

    if table is None:
        return

    # Find tbody
    tbody = None
    for child in table:
        if child.tag == 'tbody' or child.tag.endswith('}tbody'):
            tbody = child
            break

    if tbody is None:
        return

    # Get all tbody rows
    tbody_rows = [child for child in tbody if child.tag == 'tr' or child.tag.endswith('}tr')]
    if len(tbody_rows) <= num_rows_to_keep:
        return

    # Keep only last N rows
    rows_to_keep_set = set(tbody_rows[-num_rows_to_keep:])
    for row in list(tbody_rows):
        if row not in rows_to_keep_set:
            tbody.remove(row)

def rebuild_narrative_table_from_entries(section, entries, section_code, namespaces):
    """
    Rebuild the narrative table to match the filtered structured entries.
    This ensures the human-readable table matches the actual FHIR data.

    Args:
        section: The section element
        entries: The filtered entry elements to generate table rows from
        section_code: The section code (e.g., '46240-8' for Encounters)
        namespaces: XML namespaces
    """
    text_elem = section.find('hl7:text', namespaces)
    if text_elem is None:
        return

    # Find the table
    table = None
    for child in text_elem:
        if child.tag == 'table' or child.tag.endswith('}table'):
            table = child
            break

    if table is None:
        return

    # Find tbody
    tbody = None
    for child in table:
        if child.tag == 'tbody' or child.tag.endswith('}tbody'):
            tbody = child
            break

    if tbody is None:
        return

    # Clear all existing tbody rows
    for row in list(tbody):
        if row.tag == 'tr' or row.tag.endswith('}tr'):
            tbody.remove(row)

    # Rebuild rows based on section type and entries
    if section_code == '46240-8':  # Encounters
        for idx, entry in enumerate(entries, 1):
            encounter = entry.find('.//hl7:encounter', namespaces)
            if encounter is not None:
                # Extract encounter details
                code_elem = encounter.find('.//hl7:code', namespaces)
                effective_time = encounter.find('hl7:effectiveTime', namespaces)

                display_name = code_elem.get('displayName', 'Unknown') if code_elem is not None else 'Unknown'
                code_system = code_elem.get('codeSystem', '') if code_elem is not None else ''
                code_value = code_elem.get('code', '') if code_elem is not None else ''

                # Get time values
                start_time = ''
                end_time = ''
                if effective_time is not None:
                    low = effective_time.find('hl7:low', namespaces)
                    high = effective_time.find('hl7:high', namespaces)
                    if low is not None:
                        start_time = low.get('value', '')
                    if high is not None:
                        end_time = high.get('value', '')

                # Format times for display (convert YYYYMMDDHHMMSS to YYYY-MM-DDTHH:MM:SS+TZ)
                def format_time(time_str):
                    if len(time_str) >= 14:
                        return f"{time_str[0:4]}-{time_str[4:6]}-{time_str[6:8]}T{time_str[8:10]}:{time_str[10:12]}:{time_str[12:14]}+05:30"
                    return time_str

                start_display = format_time(start_time)
                end_display = format_time(end_time)

                # Create new table row
                tr = ET.Element('tr')

                # Start time
                td1 = ET.SubElement(tr, 'td')
                td1.text = start_display

                # End time
                td2 = ET.SubElement(tr, 'td')
                td2.text = end_display

                # Description
                td3 = ET.SubElement(tr, 'td')
                td3.set('ID', f'encounters-desc-{idx}')
                td3.text = display_name

                # Code
                td4 = ET.SubElement(tr, 'td')
                td4.set('ID', f'encounters-code-{idx}')
                # Convert codeSystem OID to URL
                if code_system == '2.16.840.1.113883.6.96':
                    td4.text = f'http://snomed.info/sct {code_value}'
                else:
                    td4.text = f'{code_system} {code_value}'

                tbody.append(tr)

def filter_addon_encounter_only(root, namespaces):
    """
    Filter CCDA to keep ONLY addon encounter and its resources.

    CRITICAL FILTERING LOGIC:
    This function removes ALL historical patient data and keeps ONLY resources
    generated by the ccda_addon module for the wellness visit encounter.

    The addon generates these specific resources:
    - 1 Encounter: "Encounter for check up" (SNOMED 185349003)
    - 7 Vital Signs: BP (systolic/diastolic), HR, Temp, Weight, Height, BMI, SpO2
    - 2 Lab Panels: CBC (4 components), CMP (4 components)
    - 2 Medications: Vitamin D3 (RxNorm 316672), Aspirin (RxNorm 243670)
    - 2 Procedures: Flu vaccine (SNOMED 86198006), Counseling (SNOMED 409063005)

    Strategy:
    1. Find the addon encounter by SNOMED code 185349003
    2. For each section, keep ONLY entries that match the exact addon resource specifications
    3. Remove everything else (all historical data)
    4. Filter narrative text/tables to match the filtered structured data
    """
    print_info("Filtering CCDA to keep ONLY addon encounter and its resources...")

    # ========================================================================
    # 1. ENCOUNTERS SECTION - Keep ONLY "Encounter for check up" (185349003)
    # ========================================================================
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is None:
            continue

        section_code = code_elem.get('code')

        if section_code == '46240-8':  # Encounters section
            entries = section.findall('.//hl7:entry', namespaces)
            addon_entry = None

            # Find the "Encounter for check up" entry
            for entry in entries:
                encounter = entry.find('.//hl7:encounter', namespaces)
                if encounter is not None:
                    code = encounter.find('.//hl7:code', namespaces)
                    if code is not None and code.get('code') == '185349003':
                        addon_entry = entry
                        break

            # Remove ALL entries and add back ONLY the addon encounter
            removed_count = len(entries)
            for entry in list(entries):
                section.remove(entry)

            if addon_entry is not None:
                section.append(addon_entry)
                # Rebuild narrative table from the addon entry
                rebuild_narrative_table_from_entries(section, [addon_entry], '46240-8', namespaces)
                print_info(f"  → Encounters: Kept 1 addon encounter (removed {removed_count - 1} historical)")
                print_info(f"  → Encounters: Rebuilt narrative table to match addon encounter")
            else:
                print_warning(f"  → Encounters: Addon encounter not found! Removed all {removed_count} encounters")

    # ========================================================================
    # 2. VITAL SIGNS SECTION - Keep ONLY the MOST RECENT organizer
    # ========================================================================
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is None:
            continue

        section_code = code_elem.get('code')

        if section_code == '8716-3':  # Vital Signs section
            entries = section.findall('hl7:entry', namespaces)

            if len(entries) > 0:
                removed_count = len(entries)
                # Keep ONLY the last entry (most recent vitals from addon)
                addon_vitals = entries[-1]

                # Remove all entries
                for entry in list(entries):
                    section.remove(entry)

                # Add back only the addon vitals
                section.append(addon_vitals)
                # Filter narrative table to keep only 1 row
                filter_narrative_table(section, 1, namespaces)
                print_info(f"  → Vital Signs: Kept 1 organizer with 7 vitals (removed {removed_count - 1} historical)")

    # ========================================================================
    # 3. DIAGNOSTIC RESULTS SECTION - Keep ONLY the LAST 2 panels (CBC, CMP)
    # ========================================================================
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is None:
            continue

        section_code = code_elem.get('code')

        if section_code == '30954-2':  # Diagnostic Results section
            entries = section.findall('hl7:entry', namespaces)

            if len(entries) >= 2:
                removed_count = len(entries)
                # Keep ONLY the last 2 entries (CBC and CMP from addon)
                addon_labs = entries[-2:]

                # Remove all entries
                for entry in list(entries):
                    section.remove(entry)

                # Add back only addon labs
                for entry in addon_labs:
                    section.append(entry)
                # Filter narrative table to keep only 2 rows
                filter_narrative_table(section, 2, namespaces)
                print_info(f"  → Diagnostic Results: Kept 2 panels - CBC, CMP (removed {removed_count - 2} historical)")
            elif len(entries) > 0:
                # Less than 2 entries, keep what we have
                print_info(f"  → Diagnostic Results: Kept {len(entries)} panels (expected 2)")

    # ========================================================================
    # 4. MEDICATIONS SECTION - Keep ONLY the LAST 2 medications
    # ========================================================================
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is None:
            continue

        section_code = code_elem.get('code')

        if section_code == '10160-0':  # Medications section
            entries = section.findall('hl7:entry', namespaces)

            if len(entries) >= 2:
                removed_count = len(entries)
                # Keep ONLY the last 2 medications (Vitamin D3, Aspirin from addon)
                addon_meds = entries[-2:]

                # Remove all entries
                for entry in list(entries):
                    section.remove(entry)

                # Add back only addon medications
                for entry in addon_meds:
                    section.append(entry)
                # Filter narrative table to keep only 2 rows
                filter_narrative_table(section, 2, namespaces)
                print_info(f"  → Medications: Kept 2 meds - Vitamin D3, Aspirin (removed {removed_count - 2} historical)")
            elif len(entries) > 0:
                print_info(f"  → Medications: Kept {len(entries)} meds (expected 2)")

    # ========================================================================
    # 5. PROCEDURES SECTION - Keep ONLY the LAST 2 procedures
    # ========================================================================
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is None:
            continue

        section_code = code_elem.get('code')

        if section_code == '47519-4':  # Procedures section
            entries = section.findall('hl7:entry', namespaces)

            if len(entries) >= 2:
                removed_count = len(entries)
                # Keep ONLY the last 2 procedures (Flu vaccine, Counseling from addon)
                addon_procs = entries[-2:]

                # Remove all entries
                for entry in list(entries):
                    section.remove(entry)

                # Add back only addon procedures
                for entry in addon_procs:
                    section.append(entry)
                # Filter narrative table to keep only 2 rows
                filter_narrative_table(section, 2, namespaces)
                print_info(f"  → Procedures: Kept 2 procedures - Flu vaccine, Counseling (removed {removed_count - 2} historical)")
            elif len(entries) > 0:
                print_info(f"  → Procedures: Kept {len(entries)} procedures (expected 2)")

    # ========================================================================
    # 6. ALLERGIES SECTION - Keep as-is (addon doesn't create allergies)
    # ========================================================================
    for section in root.findall('.//hl7:component//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is None:
            continue

        section_code = code_elem.get('code')

        if section_code == '48765-2':  # Allergies section
            # Addon doesn't create allergies, so this should be "No known allergies"
            print_info(f"  → Allergies: Kept as-is (no known allergies)")

    # ========================================================================
    # 7. REMOVE OTHER SECTIONS that may contain historical data
    # ========================================================================
    # Remove sections not part of addon (Problems, Immunizations, Social History, etc.)
    sections_to_keep = {'48765-2', '10160-0', '30954-2', '46240-8', '8716-3', '47519-4'}

    body = root.find('.//hl7:component//hl7:structuredBody', namespaces)
    if body is not None:
        all_sections = body.findall('hl7:component', namespaces)
        removed_sections = []

        for component in list(all_sections):
            section = component.find('hl7:section', namespaces)
            if section is not None:
                code_elem = section.find('hl7:code', namespaces)
                if code_elem is not None:
                    section_code = code_elem.get('code')
                    section_name = code_elem.get('displayName', 'Unknown')

                    # Remove sections NOT in the addon
                    if section_code not in sections_to_keep:
                        body.remove(component)
                        removed_sections.append(section_name)

        if removed_sections:
            print_info(f"  → Removed {len(removed_sections)} non-addon sections: {', '.join(removed_sections[:3])}...")

    print_success("COMPLETE: CCDA now contains ONLY addon encounter resources")
    print_success("All historical patient data has been removed")
    return root

def add_component_of_section(root, encounter_date, patient_id, namespaces):
    """
    Add componentOf/encompassingEncounter section to CCDA XML.
    This is REQUIRED by TRDataServices parseEncounter method.

    The componentOf section wraps the primary encounter that the document describes.
    Without this, the loadCCDAFromXML endpoint will return null and fail.

    Args:
        root: ElementTree root
        encounter_date: Encounter date string (YYYY-MM-DD)
        patient_id: Patient ID for generating unique encounter ID
        namespaces: XML namespaces dict
    """
    print_info("Adding componentOf/encompassingEncounter section...")

    # Parse encounter date and format for CCDA (YYYYMMDD - backend can parse this format)
    # Note: Using yyyyMMdd instead of yyyyMMddHHmmss because backend Utils.parseDateWithUnknownFormat()
    # only supports yyyyMMdd format (see Utils.java:43)
    dt = datetime.strptime(encounter_date, '%Y-%m-%d')
    ccda_date_low = dt.strftime('%Y%m%d')  # yyyyMMdd format
    ccda_date_high = dt.strftime('%Y%m%d')  # yyyyMMdd format

    # Generate unique encounter ID
    encounter_id = f"{patient_id}addon{dt.strftime('%Y%m%d')}"

    # Find the insertion point (after documentationOf, before component/structuredBody)
    # Find documentationOf element
    documentation_of = root.find('hl7:documentationOf', namespaces)
    if documentation_of is None:
        print_warning("documentationOf not found, will insert componentOf before component")
        insert_index = None
        for idx, child in enumerate(root):
            if child.tag == '{urn:hl7-org:v3}component':
                insert_index = idx
                break
    else:
        # Get index of documentationOf to insert after it
        insert_index = list(root).index(documentation_of) + 1

    # Create componentOf element
    component_of = ET.Element('{urn:hl7-org:v3}componentOf')

    # Create encompassingEncounter with moodCode="EVN" (indicates completed encounter)
    encompassing_encounter = ET.SubElement(component_of, '{urn:hl7-org:v3}encompassingEncounter')
    encompassing_encounter.set('classCode', 'ENC')  # ENC = Encounter
    encompassing_encounter.set('moodCode', 'EVN')  # EVN = event/completed encounter

    # Add encounter ID
    enc_id = ET.SubElement(encompassing_encounter, '{urn:hl7-org:v3}id')
    enc_id.set('root', '2.16.840.1.113883.19.5')
    enc_id.set('extension', encounter_id)

    # Add encounter code (ambulatory - outpatient encounter with specific type)
    enc_code = ET.SubElement(encompassing_encounter, '{urn:hl7-org:v3}code')
    enc_code.set('code', 'AMB')
    enc_code.set('codeSystem', '2.16.840.1.113883.5.4')
    enc_code.set('displayName', 'Ambulatory')
    enc_code.set('codeSystemName', 'ActEncounterCode')

    # Add translation with specific encounter type (wellness visit/check up)
    # This provides the detailed encounter type beyond just the class
    translation = ET.SubElement(enc_code, '{urn:hl7-org:v3}translation')
    translation.set('code', '185349003')
    translation.set('codeSystem', '2.16.840.1.113883.6.96')  # SNOMED-CT
    translation.set('displayName', 'Encounter for check up (procedure)')
    translation.set('codeSystemName', 'SNOMED-CT')

    # Add effective time (encounter period)
    effective_time = ET.SubElement(encompassing_encounter, '{urn:hl7-org:v3}effectiveTime')
    low = ET.SubElement(effective_time, '{urn:hl7-org:v3}low')
    low.set('value', ccda_date_low)
    high = ET.SubElement(effective_time, '{urn:hl7-org:v3}high')
    high.set('value', ccda_date_high)

    # Insert componentOf at the correct position
    if insert_index is not None:
        root.insert(insert_index, component_of)
    else:
        # Fallback: append before the last element (component/structuredBody)
        root.insert(len(root) - 1, component_of)

    print_success(f"Added componentOf section with encounter ID: {encounter_id}")
    print_info(f"  - Mood code: EVN (completed encounter)")
    print_info(f"  - Encounter code: AMB (Ambulatory)")
    print_info(f"  - Encounter period: {ccda_date_low} to {ccda_date_high}")

    return root

def convert_all_dates_to_yyyyMMdd(root, namespaces):
    """
    Convert ALL date values in the XML from yyyyMMddHHmmss to yyyyMMdd format.

    EXCEPT: Keep full timestamps in procedure table "Date" column cells AND append timezone.
    Backend createProcedures() uses CCDACommonUtils.formatDate() which requires
    full "yyyyMMddHHmmssZ" format (e.g., "20251022000000+0000").

    Args:
        root: ElementTree root
        namespaces: XML namespaces dict
    """
    print_info("Converting dates to yyyyMMdd format (procedure dates will keep timestamps with timezone)...")

    # First, find all table cells in procedure section that contain dates
    # These cells are in the "Date" column and need to keep full timestamps
    procedure_date_cells = set()

    # Find procedure section by code 47519-4
    for section in root.findall('.//{*}section'):
        code_elem = section.find('.//{*}code')
        if code_elem is not None and code_elem.get('code') == '47519-4':
            # Found procedure section, now find its table
            table = section.find('.//{*}table')
            if table is not None:
                # Find header row to locate "Date" column index
                thead = table.find('{*}thead')
                if thead is not None:
                    header_row = thead.find('{*}tr')
                    if header_row is not None:
                        headers = [th.text.strip() if th.text else '' for th in header_row.findall('{*}th')]
                        # Find Date column index (case insensitive)
                        date_col_idx = None
                        for idx, header in enumerate(headers):
                            if header.lower() == 'date':
                                date_col_idx = idx
                                break

                        if date_col_idx is not None:
                            # Now find all cells in that column and mark them
                            tbody = table.find('{*}tbody')
                            if tbody is not None:
                                for row in tbody.findall('{*}tr'):
                                    cells = row.findall('{*}td')
                                    if date_col_idx < len(cells):
                                        # Mark this cell's text content for preservation
                                        date_cell = cells[date_col_idx]
                                        if date_cell.text:
                                            procedure_date_cells.add(id(date_cell))

                            print_info(f"  → Found {len(procedure_date_cells)} procedure date cells to preserve")

    # Collect all elements in procedure section to skip (and later add timezone)
    procedure_elements_to_skip = set()
    for section in root.findall('.//{*}section'):
        code_elem = section.find('.//{*}code')
        if code_elem is not None and code_elem.get('code') == '47519-4':
            # This is the procedure section - collect all elements
            for elem in section.iter():
                procedure_elements_to_skip.add(id(elem))
            print_info(f"  → Found procedure section with {len(procedure_elements_to_skip)} elements to preserve")

    # Now convert all date attributes
    date_count = 0
    procedure_date_count = 0

    for elem in root.iter():
        # Check if element has a 'value' attribute that looks like a date
        value = elem.get('value')
        if value and len(value) >= 8:
            # Check if it's a date in yyyyMMddHHmmss format (14+ digits)
            if value.isdigit() and len(value) > 8:
                # If this element is in procedure section, add timezone instead of truncating
                if id(elem) in procedure_elements_to_skip:
                    # Keep full timestamp and append timezone "+0000"
                    if not value.endswith('+0000') and len(value) == 14:
                        new_value = value + '+0000'  # yyyyMMddHHmmss+0000
                        elem.set('value', new_value)
                        procedure_date_count += 1
                    continue

                # Extract just the yyyyMMdd part (first 8 digits)
                new_value = value[:8]
                elem.set('value', new_value)
                date_count += 1

    if date_count > 0:
        print_success(f"Converted {date_count} dates to yyyyMMdd format")
    if procedure_date_count > 0:
        print_success(f"Added timezone to {procedure_date_count} procedure dates (format: yyyyMMddHHmmss+0000)")

    return root

def fix_medications_section_code(root, namespaces):
    """
    Change medications section code from "10160-0" to "29549-3".

    Backend processSections() expects "29549-3" (Medications Administered),
    but Synthea generates "10160-0" (History of medication use).

    Args:
        root: ElementTree root
        namespaces: XML namespaces dict
    """
    print_info("Fixing medications section code...")

    for section in root.findall('.//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is not None and code_elem.get('code') == '10160-0':
            # Change to Medications at Discharge (10183-2) which backend handles
            # Backend expects: "Medication", "Sig", "Dispensed", "Refills", "Start Date", "End Date"
            code_elem.set('code', '10183-2')
            code_elem.set('displayName', 'Hospital discharge medications')
            code_elem.set('codeSystemName', 'LOINC')

            # Update title if present
            title = section.find('hl7:title', namespaces)
            if title is not None:
                title.text = 'Medications'

            print_success("Changed medication section code: 10160-0 → 10183-2")
            return root

    print_warning("Medications section (10160-0) not found")
    return root

def add_thetarho_identifiers_to_resources(root, base_identifier, practice_id, namespaces):
    """
    Add ThetaRho identifier to ALL clinical resources in the CCDA.

    This is CRITICAL - the backend upsertCCDAResource() method requires resources to have
    a "ThetaRho" identifier system, otherwise it returns null and resources aren't created.

    Format: a-{practice_id}.E-{patient_id}-{resource_type}-{resource_id}

    Args:
        root: ElementTree root
        base_identifier: Base identifier (e.g., "a-11783.E-t1210-t1210_addon")
        practice_id: Practice ID (e.g., "11783")
        namespaces: XML namespaces dict
    """
    print_info("Adding ThetaRho identifiers to all resources...")

    resource_count = 0

    # Resource type mapping from CCDA clinical statement class codes
    resource_type_map = {
        'substanceAdministration': 'MedicationRequest',
        'procedure': 'Procedure',
        'observation': 'Observation',
        'organizer': 'DiagnosticReport',  # Organizers typically become DiagnosticReports
        'act': 'Procedure',
    }

    # Find all entry elements (these contain clinical resources)
    for section in root.findall('.//hl7:section', namespaces):
        for entry in section.findall('.//hl7:entry', namespaces):
            # Find the clinical statement element (substanceAdministration, procedure, observation, etc.)
            for child in entry:
                # Remove namespace from tag to get element name
                element_name = child.tag.replace('{urn:hl7-org:v3}', '')

                if element_name in resource_type_map:
                    resource_type = resource_type_map[element_name]

                    # Check if element already has an id
                    existing_ids = child.findall('hl7:id', namespaces)

                    # Get the first existing ID (check both extension and root attributes)
                    resource_id = None
                    for id_elem in existing_ids:
                        # After UUID replacement, ID is in 'root' attribute (not 'extension')
                        resource_id = id_elem.get('extension') or id_elem.get('root')
                        if resource_id:
                            break

                    if not resource_id:
                        # No existing ID, skip
                        continue

                    # Generate athenaId using the same pattern as convert_to_athena_format.py
                    athena_prefix = ATHENA_ID_PREFIXES.get(resource_type, 'unknown')
                    athena_id = f"a-{practice_id}.{athena_prefix}-{resource_id}"

                    # Add ThetaRho identifier
                    thetarho_id = ET.Element('{urn:hl7-org:v3}id')
                    thetarho_id.set('root', 'ThetaRho')
                    thetarho_id.set('extension', athena_id)

                    # Insert at the beginning (after existing ids)
                    insert_pos = len(existing_ids)
                    child.insert(insert_pos, thetarho_id)

                    resource_count += 1

    print_success(f"Added ThetaRho identifiers to {resource_count} resources")
    return root

def get_dr_subtype_from_loinc(loinc_code, display_name=''):
    """
    Map LOINC code to dr_subtype tag value.

    This mapping matches the logic in convert_to_athena_format.py
    and ensures DiagnosticReports have the correct dr_subtype tag
    so Q&A queries like "latest CBC" can find them.

    Args:
        loinc_code: LOINC code (e.g., "58410-2")
        display_name: Display name for keyword-based fallback detection

    Returns:
        dr_subtype value (e.g., "drCBC", "drCMP", "drHBA1C", etc.)
    """
    # LOINC code to dr_subtype mapping
    # Source: convert_to_athena_format.py lines 821-845
    loinc_subtype_map = {
        # Basic Metabolic Panel
        '24320-4': 'drBMP',
        '24321-2': 'drBMP',
        '51990-0': 'drBMP',
        '70219-1': 'drBMP',
        '89044-2': 'drBMP',

        # Complete Blood Count
        '58410-2': 'drCBC',
        '57021-8': 'drCBC',
        '57782-5': 'drCBC',
        '69742-5': 'drCBC',

        # Comprehensive Metabolic Panel
        '24322-0': 'drCMP',
        '24323-8': 'drCMP',

        # Hemoglobin A1c
        '4548-4': 'drHBA1C',

        # Lipid Panel
        '57698-3': 'drLP',
        '24331-1': 'drLP',

        # STI Panel
        '24111-7': 'drSTI',

        # Thyroid Stimulating Hormone
        '3016-3': 'drTSH',

        # Urinalysis
        '24356-8': 'drUA',
        '24357-6': 'drUA'
    }

    # Try LOINC code lookup first
    if loinc_code in loinc_subtype_map:
        return loinc_subtype_map[loinc_code]

    # Keyword-based fallback detection
    # Source: convert_to_athena_format.py lines 848-870
    if display_name:
        text_lower = display_name.lower()

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

    return 'drOTHER'

def restructure_results_section_for_backend(root, namespaces):
    """
    Restructure Results section (30954-2) with <list><item><table> format.

    CRITICAL: Backend processProcedureResults() method expects lab observations in a specific format:
    - <text><list><item><table> structure (NOT standard CCDA organizer/component)
    - Each <item> contains a <caption> (panel name) and <table> with observation rows
    - Backend parses observations from TABLE ROWS, not from <entry><organizer> elements

    This function:
    1. Extracts observations from existing <organizer><component> elements
    2. Creates <list><item><table> structure in <text> element
    3. Keeps the standard CCDA <organizer> entries for compliance

    Args:
        root: ElementTree root
        namespaces: XML namespaces dict

    Returns:
        Modified root element
    """
    print_info("Restructuring Results section with list/item/table for backend compatibility...")

    # Find Results section (code 30954-2)
    for section in root.findall('.//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is None or code_elem.get('code') != '30954-2':
            continue

        print_info("  → Found Results section (30954-2)")

        # Parse organizers to extract observations
        organizers_data = []
        for entry in section.findall('.//hl7:entry', namespaces):
            organizer = entry.find('hl7:organizer', namespaces)
            if organizer is None:
                continue

            # Get organizer details
            org_code = organizer.find('hl7:code', namespaces)
            org_id = organizer.find('hl7:id', namespaces)
            org_time = organizer.find('hl7:effectiveTime', namespaces)

            if org_code is None:
                continue

            panel_name = org_code.get('displayName', 'Unknown Panel')
            panel_code = org_code.get('code', '')

            # Extract time
            time_low = org_time.find('hl7:low', namespaces) if org_time is not None else None
            time_value = time_low.get('value', '') if time_low is not None else ''

            # Parse all component observations
            observations = []
            for component in organizer.findall('hl7:component', namespaces):
                obs = component.find('hl7:observation', namespaces)
                if obs is None:
                    continue

                obs_code = obs.find('hl7:code', namespaces)
                obs_value = obs.find('hl7:value', namespaces)

                if obs_code is not None and obs_value is not None:
                    obs_data = {
                        'name': obs_code.get('displayName', 'Unknown'),
                        'code': obs_code.get('code', ''),
                        'value': obs_value.get('value', ''),
                        'unit': obs_value.get('unit', ''),
                    }
                    observations.append(obs_data)

            if observations:
                organizers_data.append({
                    'name': panel_name,
                    'code': panel_code,
                    'time': time_value,
                    'observations': observations,
                })

        if not organizers_data:
            print_info("  → No organizers found with observations, skipping")
            continue

        print_info(f"  → Extracted {len(organizers_data)} diagnostic panels")
        for org in organizers_data:
            print_info(f"    - {org['name']} (LOINC: {org['code']}): {len(org['observations'])} observations")

        # Create new <text> element with <list><item><table> structure
        text_elem = section.find('hl7:text', namespaces)
        if text_elem is None:
            text_elem = ET.Element('{urn:hl7-org:v3}text')
            section.insert(2, text_elem)  # Insert after title
        else:
            # Clear existing content
            text_elem.clear()
            text_elem.tag = '{urn:hl7-org:v3}text'

        # Create <list> element
        list_elem = ET.SubElement(text_elem, '{urn:hl7-org:v3}list')

        # Create <item> for each organizer (panel)
        for idx, org_data in enumerate(organizers_data, 1):
            item_elem = ET.SubElement(list_elem, '{urn:hl7-org:v3}item')

            # Add caption - use exact component name from database titleLoincMap
            # Backend's loincCodesService.findLoincCode() requires exact match for successful lookup
            # Both component and long_common_name fields are added to titleLoincMap (LoincCodesService.java:69-70)
            caption_elem = ET.SubElement(item_elem, '{urn:hl7-org:v3}caption')

            # Get LOINC code and use mapping to find correct component name
            loinc_code = org_data.get('code', '')
            original_name = org_data.get('name', '')

            # Use get_caption_for_loinc() to get database component name
            # Falls back to original display name if LOINC not in mapping
            caption_text = get_caption_for_loinc(loinc_code, original_name)

            # Append date to caption for backend extractDateFromString() to parse
            # Backend expects format: (MM/DD/YYYY HH:MM AM/PM TZ)
            # See CCDACommonUtils.findDateMatcher() for regex patterns
            org_time = org_data.get('time', '')
            if org_time:
                # Parse time_value format: YYYYMMDD or YYYYMMDDHHMMSS
                try:
                    if len(org_time) >= 8:
                        year = org_time[0:4]
                        month = org_time[4:6]
                        day = org_time[6:8]
                        # Format as (MM/DD/YYYY 12:00 AM EST)
                        date_str = f"({month}/{day}/{year} 12:00 AM EST)"
                        caption_text = f"{caption_text} {date_str}"
                except Exception as e:
                    print_warning(f"Could not parse time value '{org_time}': {e}")

            caption_elem.text = caption_text

            # Create table
            table_elem = ET.SubElement(item_elem, '{urn:hl7-org:v3}table')
            table_elem.set('border', '1')
            table_elem.set('width', '100%')

            # Table header - MUST match backend expectations
            # Backend looks for: "Component" and "Ref Range" (case-insensitive)
            thead_elem = ET.SubElement(table_elem, '{urn:hl7-org:v3}thead')
            header_row = ET.SubElement(thead_elem, '{urn:hl7-org:v3}tr')
            for header in ['Component', 'Value', 'Ref Range']:
                th = ET.SubElement(header_row, '{urn:hl7-org:v3}th')
                th.text = header

            # Table body with observations
            tbody_elem = ET.SubElement(table_elem, '{urn:hl7-org:v3}tbody')
            for obs_idx, obs in enumerate(org_data['observations'], 1):
                row = ET.SubElement(tbody_elem, '{urn:hl7-org:v3}tr')
                row.set('ID', f'panel-{idx}-obs-{obs_idx}')

                # Component (observation display name - backend uses this as observation name)
                # Backend's createNonVitalObservation() uses this value as the display text
                td_component = ET.SubElement(row, '{urn:hl7-org:v3}td')
                td_component.text = obs['name']

                # Value (with unit)
                td_value = ET.SubElement(row, '{urn:hl7-org:v3}td')
                value_with_unit = f"{obs['value']} {obs['unit']}" if obs['unit'] else obs['value']
                td_value.text = value_with_unit

                # Ref Range (empty for now - TODO: get actual reference ranges like "4.5-11.0")
                td_ref_range = ET.SubElement(row, '{urn:hl7-org:v3}td')
                td_ref_range.text = ""

        print_success(f"Restructured Results section with {len(organizers_data)} panels containing {sum(len(org['observations']) for org in organizers_data)} total observations")
        break  # Only one Results section expected

    return root


def transform_table_headers_for_backend(root, namespaces):
    """
    Transform narrative table headers AND row data to match TRDataServices expected format.

    CRITICAL: The backend parser reads narrative HTML tables (not structured entries).
    We must REBUILD the entire table structure (headers + rows) to match what backend expects.

    The backend expects SPECIFIC column orders and names:
    - Vitals: "Vital Sign", "Reading", "Time Taken", "Comments"
    - Medications: "Date of Administration", "Medication", "Notes"
    - Procedures: "Procedure Name", "Description"
    - Diagnostic Results: "Component", "Ref Range"

    Synthea generates: Start, Stop, Description, Code, Value (5 columns)
    We must REORDER the row cells to match the expected backend column order.

    Args:
        root: ElementTree root
        namespaces: XML namespaces dict
    """
    print_info("Transforming table headers and row data to match backend expectations...")

    # Define expected output structure for each section
    # Format: section_code -> list of (output_column_name, source_column_name)
    transformations = {
        # Vitals section (code: 8716-3)
        # Backend looks for: "Vital Sign", "Reading", "Time Taken", "Comments" (case-insensitive)
        # Synthea has: Start, Stop, Description, Code, Value
        '8716-3': [
            ('Vital Sign', 'Description'),  # Vital name (will transform long → short name)
            ('Reading', 'Value'),           # Vital value (e.g., "99.3 %")
            ('Time Taken', 'Start'),        # Timestamp
            ('Comments', 'Code')            # LOINC code as comment
        ],

        # Medications section (code: 10183-2 - MEDICATION_AT_DISCHARGE)
        # Backend expects: Medication, Sig, Dispensed, Refills, Start Date, End Date
        # Synthea has: Start, Stop, Description, Code
        # NOTE: Synthea doesn't provide Sig/Dispensed/Refills in narrative table
        # We'll create synthetic values to avoid backend parsing errors
        '10183-2': [
            ('Medication', 'Description'),
            ('Sig', None),           # Will synthesize "Take 1 tablet by mouth daily"
            ('Dispensed', None),     # Will synthesize "30 tablet"
            ('Refills', None),       # Will synthesize "3"
            ('Start Date', 'Start'),
            ('End Date', 'Stop')
        ],

        # Procedures section (code: 47519-4)
        # Backend expects: Procedure Name, Description
        '47519-4': [
            ('Procedure Name', 'Description'),
            ('Description', 'Code')
        ],

        # Diagnostic Results section (code: 30954-2)
        # Backend expects: Component, Ref Range
        '30954-2': [
            ('Component', 'Description'),
            ('Ref Range', 'Code')
        ]
    }

    # Vital sign name mappings (long LOINC descriptions → backend short names)
    vital_sign_mappings = {
        'Oxygen saturation in Arterial blood by Pulse oximetry': 'Oxygen Saturation',
        'Body Height': 'Height',
        'Body height': 'Height',
        'Body Weight': 'Weight',
        'Body weight': 'Weight',
        'Body mass index (BMI) [Ratio]': 'Body Mass Index',
        'Body Mass Index (BMI) [Ratio]': 'Body Mass Index',
        'Heart rate': 'Pulse',
        'Heart Rate': 'Pulse',
        'Respiratory rate': 'Respiratory Rate',
        'Body temperature': 'Temperature',
        'Body Temperature': 'Temperature',
        'Systolic blood pressure': 'Blood Pressure Systolic',
        'Diastolic blood pressure': 'Blood Pressure Diastolic',
        'Blood pressure': 'Blood Pressure'
    }

    sections_transformed = 0

    for section in root.findall('.//hl7:section', namespaces):
        code_elem = section.find('hl7:code', namespaces)
        if code_elem is None:
            continue

        section_code = code_elem.get('code')
        if section_code not in transformations:
            continue

        # CRITICAL: Skip Results section - already transformed by restructure_results_section_for_backend()
        # If we transform it again, it will clear the cell values
        if section_code == '30954-2':
            print_info(f"  → Skipping Results section (already restructured with list/item/table)")
            continue

        # Find the narrative text/table
        text_elem = section.find('hl7:text', namespaces)
        if text_elem is None:
            continue

        table = text_elem.find('.//hl7:table', namespaces)
        if table is None:
            continue

        thead = table.find('hl7:thead', namespaces)
        tbody = table.find('hl7:tbody', namespaces)
        if thead is None or tbody is None:
            continue

        # Get current header row
        old_header_row = thead.find('hl7:tr', namespaces)
        if old_header_row is None:
            continue

        # Build mapping of old column names to indices
        # CRITICAL: Strip newlines from header names that Synthea generates
        old_headers = [th.text.replace('\n', '').replace('\r', '').strip() if th.text else ''
                       for th in old_header_row.findall('hl7:th', namespaces)]
        old_header_map = {name: idx for idx, name in enumerate(old_headers)}

        # Get transformation spec for this section
        new_structure = transformations[section_code]

        # STEP 1: Rebuild header row
        # First, remove ALL children and text (including whitespace nodes)
        for th in old_header_row.findall('hl7:th', namespaces):
            old_header_row.remove(th)

        # CRITICAL: Remove whitespace text nodes that MDHT parser picks up
        old_header_row.text = None
        old_header_row.tail = None

        for new_col_name, _ in new_structure:
            new_th = ET.Element(f'{{{namespaces["hl7"]}}}th')
            new_th.text = new_col_name
            new_th.tail = None  # No whitespace after element
            old_header_row.append(new_th)

        # STEP 2: Rebuild each tbody row
        for row in tbody.findall('hl7:tr', namespaces):
            # Get all old cell values
            old_cells = row.findall('hl7:td', namespaces)
            old_values = []
            old_ids = []

            for td in old_cells:
                # CRITICAL: Strip newlines and whitespace that backend can't handle
                cell_value = td.text if td.text else ''
                cell_value = cell_value.replace('\n', '').replace('\r', '').strip()
                old_values.append(cell_value)
                old_ids.append(td.get('ID', ''))

            # Remove all old cells
            for td in old_cells:
                row.remove(td)

            # CRITICAL: Remove whitespace text nodes
            row.text = None
            row.tail = None

            # Create new cells in the expected order
            for new_col_name, source_col_name in new_structure:
                new_td = ET.Element(f'{{{namespaces["hl7"]}}}td')

                # Handle columns with no source (None) - synthesize values
                if source_col_name is None:
                    # Synthesize medication-specific values to avoid backend parsing errors
                    if section_code == '10183-2':
                        if new_col_name == 'Sig':
                            new_td.text = 'Take 1 tablet by mouth daily'
                        elif new_col_name == 'Dispensed':
                            new_td.text = '90 tablet'
                        elif new_col_name == 'Refills':
                            new_td.text = '3'
                        else:
                            new_td.text = ''
                    else:
                        new_td.text = ''
                    new_td.tail = None
                # Get value from source column
                elif source_col_name in old_header_map:
                    source_idx = old_header_map[source_col_name]
                    if source_idx < len(old_values):
                        value = old_values[source_idx]

                        # Special handling: Transform vital sign names for vitals section
                        if section_code == '8716-3' and new_col_name == 'Vital Sign':
                            for long_desc, short_name in vital_sign_mappings.items():
                                if long_desc.lower() in value.lower():
                                    value = short_name
                                    break

                        new_td.text = value
                        new_td.tail = None  # No whitespace after element

                        # Preserve ID attribute if present
                        if source_idx < len(old_ids) and old_ids[source_idx]:
                            new_td.set('ID', old_ids[source_idx])
                else:
                    new_td.text = ''
                    new_td.tail = None

                row.append(new_td)

        # CRITICAL: Remove ALL whitespace-only text nodes AND strip newlines from content
        # The MDHT parser picks up whitespace as separate items in the headers list
        # AND backend can't handle newlines in cell content
        def remove_whitespace_nodes(element):
            """Recursively remove whitespace-only text and strip newlines from content"""
            if element.text:
                if not element.text.strip():
                    element.text = None
                else:
                    # Strip newlines and excess whitespace from content
                    element.text = element.text.replace('\n', '').replace('\r', '').strip()
            if element.tail:
                if not element.tail.strip():
                    element.tail = None
                else:
                    element.tail = element.tail.replace('\n', '').replace('\r', '').strip()
            for child in element:
                remove_whitespace_nodes(child)

        remove_whitespace_nodes(table)

        sections_transformed += 1
        section_name = code_elem.get('displayName', section_code)
        print_success(f"  ✓ Rebuilt {section_name} table structure")

    # CRITICAL: Remove Encounters section entirely - it causes backend errors
    # The componentOf element already provides encounter information
    print_info("Removing Encounters section (causes backend errors)...")
    structured_body = root.find('.//hl7:structuredBody', namespaces)
    if structured_body is not None:
        for component in structured_body.findall('hl7:component', namespaces):
            section = component.find('hl7:section', namespaces)
            if section is not None:
                code_elem = section.find('hl7:code', namespaces)
                if code_elem is not None and code_elem.get('code') == '46240-8':
                    structured_body.remove(component)
                    print_success("  ✓ Removed Encounters section")
                    break

    if sections_transformed > 0:
        print_success(f"Transformed {sections_transformed} section table(s)")
    else:
        print_info("No tables found requiring transformation")

    return root

# ============================================================================
# API Functions
# ============================================================================
def fetch_patient_from_fhir(base_url, patient_id):
    """
    Fetch patient data from HAPI FHIR server
    Args:
        base_url: Base server URL without port (e.g., 'danvers-clone.thetarho.com')
        patient_id: Patient ID (e.g., 't1210')
    """
    try:
        # Construct HAPI FHIR URL
        # Handle if base_url already contains http:// or port
        if base_url.startswith('http://') or base_url.startswith('https://'):
            fhir_url = base_url
        elif ':' in base_url:
            # URL already has port, just add http://
            fhir_url = f"http://{base_url}"
        else:
            # Plain hostname, add http:// and :8080/fhir
            fhir_url = f"http://{base_url}:8080/fhir"

        url = f"{fhir_url}/Patient?identifier={patient_id}"

        print_info(f"Fetching patient from: {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        bundle = response.json()

        if bundle.get('total', 0) == 0:
            print_error(f"Patient {patient_id} not found in FHIR server")
            return None

        patient = bundle['entry'][0]['resource']
        name = patient.get('name', [{}])[0]
        given_name = ' '.join(name.get('given', ['']))
        family_name = name.get('family', '')
        print_success(f"Found patient: {given_name} {family_name}")

        return patient

    except requests.exceptions.RequestException as e:
        print_error(f"Failed to fetch patient from FHIR: {e}")
        return None

def fetch_organization_from_fhir(base_url, patient_data):
    """
    Fetch organization data from HAPI FHIR server.
    Tries multiple sources in order:
    1. Patient's managing organization
    2. Patient's most recent encounter's service provider
    3. Patient's general practitioner's organization (via PractitionerRole)

    Args:
        base_url: Base server URL without port (e.g., 'danvers-clone.thetarho.com')
        patient_data: Patient resource
    """
    try:
        # Construct HAPI FHIR URL
        # Handle if base_url already contains http:// or port
        if base_url.startswith('http://') or base_url.startswith('https://'):
            fhir_url = base_url
        elif ':' in base_url:
            # URL already has port, just add http://
            fhir_url = f"http://{base_url}"
        else:
            # Plain hostname, add http:// and :8080/fhir
            fhir_url = f"http://{base_url}:8080/fhir"

        patient_id = patient_data.get('id', '')

        # Try 1: Get managing organization from patient
        managing_org = patient_data.get('managingOrganization')
        if managing_org and managing_org.get('reference'):
            org_reference = managing_org.get('reference')
            print_info(f"Using managing organization: {org_reference}")

            if org_reference.startswith('http'):
                url = org_reference
            elif org_reference.startswith('Organization/'):
                org_id = org_reference.split('/')[-1]
                url = f"{fhir_url}/Organization/{org_id}"
            else:
                url = f"{fhir_url}/{org_reference}"

            response = requests.get(url, timeout=30)
            response.raise_for_status()
            organization = response.json()
            org_name = organization.get('name', 'Unknown Practice')
            print_success(f"Found organization: {org_name}")
            return {'name': org_name, 'id': organization.get('id', '')}

        # Try 2: Get organization from most recent encounter's serviceProvider
        print_info("No managing organization, checking recent encounters...")
        encounter_url = f"{fhir_url}/Encounter?patient=Patient/{patient_id}&_count=1&_sort=-date"
        response = requests.get(url=encounter_url, timeout=30)
        response.raise_for_status()

        encounter_bundle = response.json()
        # Check for entries instead of total (total might be missing or 0)
        if 'entry' in encounter_bundle and len(encounter_bundle['entry']) > 0:
            encounter = encounter_bundle['entry'][0]['resource']
            service_provider = encounter.get('serviceProvider')

            if service_provider and service_provider.get('reference'):
                org_reference = service_provider.get('reference')
                org_display = service_provider.get('display', '')
                print_info(f"Using encounter service provider: {org_display or org_reference}")

                if org_reference.startswith('http'):
                    url = org_reference
                elif org_reference.startswith('Organization/'):
                    org_id = org_reference.split('/')[-1]
                    url = f"{fhir_url}/Organization/{org_id}"
                else:
                    url = f"{fhir_url}/{org_reference}"

                response = requests.get(url, timeout=30)
                response.raise_for_status()
                organization = response.json()
                org_name = organization.get('name', org_display or 'Unknown Practice')
                print_success(f"Found organization: {org_name}")
                return {'name': org_name, 'id': organization.get('id', '')}

        # Try 3: Get organization from general practitioner
        general_practitioners = patient_data.get('generalPractitioner', [])
        if general_practitioners:
            for gp in general_practitioners:
                gp_ref = gp.get('reference', '')
                if 'Practitioner/' in gp_ref:
                    practitioner_id = gp_ref.split('/')[-1]
                    print_info(f"Checking general practitioner: {practitioner_id}")

                    # Get PractitionerRole to find organization
                    pr_url = f"{fhir_url}/PractitionerRole?practitioner={practitioner_id}"
                    response = requests.get(pr_url, timeout=30)
                    response.raise_for_status()

                    pr_bundle = response.json()
                    if pr_bundle.get('total', 0) > 0:
                        pr = pr_bundle['entry'][0]['resource']
                        org = pr.get('organization')
                        if org and org.get('reference'):
                            org_reference = org.get('reference')
                            org_display = org.get('display', '')
                            print_info(f"Using practitioner's organization: {org_display or org_reference}")

                            if org_reference.startswith('Organization/'):
                                org_id = org_reference.split('/')[-1]
                                url = f"{fhir_url}/Organization/{org_id}"

                                response = requests.get(url, timeout=30)
                                response.raise_for_status()
                                organization = response.json()
                                org_name = organization.get('name', org_display or 'Unknown Practice')
                                print_success(f"Found organization: {org_name}")
                                return {'name': org_name, 'id': organization.get('id', '')}

        print_warning("Could not find organization from any source")
        return {'name': 'Unknown Practice'}

    except requests.exceptions.RequestException as e:
        print_warning(f"Could not fetch organization data: {e}")
        return {'name': 'Unknown Practice'}

# ============================================================================
# Synthea Generation Functions
# ============================================================================
def move_addon_to_modules():
    """
    Move ccda_addon.json from custom_modules to modules folder
    """
    source = os.path.join(CUSTOM_MODULES_DIR, ADDON_MODULE_NAME)
    dest = os.path.join(MODULES_DIR, ADDON_MODULE_NAME)

    if not os.path.exists(source):
        print_error(f"Addon module not found: {source}")
        return False

    try:
        shutil.copy2(source, dest)
        print_success(f"Copied addon module to modules folder")
        return True
    except Exception as e:
        print_error(f"Failed to copy addon module: {e}")
        return False

def generate_synthea_ccda():
    """
    Generate CCDA using Synthea (no -m flag, uses module from modules folder)
    Returns path to generated CCDA file
    """
    try:
        # Clean output directory
        if os.path.exists(OUTPUT_CCDA_DIR):
            for file in glob.glob(os.path.join(OUTPUT_CCDA_DIR, '*.xml')):
                os.remove(file)
            print_info("Cleaned previous CCDA output files")

        # Run Synthea WITHOUT -m flag (uses modules folder)
        print_info("Running Synthea to generate CCDA...")

        cmd = [
            './run_synthea',
            '-p', '1',      # Generate 1 patient
            '-a', '20-22',  # Age 20-22 (minimal history)
            'Massachusetts'  # State parameter
        ]

        result = subprocess.run(
            cmd,
            cwd=SYNTHEA_DIR,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            print_error(f"Synthea generation failed")
            print_error(f"STDERR: {result.stderr}")
            return None

        # Find generated CCDA file
        ccda_files = glob.glob(os.path.join(OUTPUT_CCDA_DIR, '*.xml'))

        if not ccda_files:
            print_error("No CCDA file generated")
            return None

        ccda_file = ccda_files[0]
        print_success(f"Generated CCDA: {os.path.basename(ccda_file)}")

        return ccda_file

    except subprocess.TimeoutExpired:
        print_error("Synthea generation timed out")
        return None
    except Exception as e:
        print_error(f"Synthea generation failed: {e}")
        return None

def cleanup_addon_from_modules():
    """
    Remove addon module from modules folder
    """
    addon_path = os.path.join(MODULES_DIR, ADDON_MODULE_NAME)

    try:
        if os.path.exists(addon_path):
            os.remove(addon_path)
            print_success("Removed addon module from modules folder")
        return True
    except Exception as e:
        print_warning(f"Could not remove addon module: {e}")
        return False

# ============================================================================
# XML Processing Functions
# ============================================================================
def process_ccda_xml(ccda_file, patient_data, practice_data, patient_id, practice_id, encounter_date):
    """
    Process CCDA XML file:
    1. Parse XML
    2. Update patient demographics
    3. Update encounter dates
    4. Filter to keep only addon encounter
    5. Convert all dates to yyyyMMdd format
    6. Fix medications section code
    7. Add componentOf section
    8. Build UUID mapping
    9. Replace UUIDs in XML content
    10. Add ThetaRho identifiers to resources
    11. Transform table headers for backend parser
    12. Return processed XML content
    """
    try:
        # Define namespaces
        namespaces = {
            'hl7': 'urn:hl7-org:v3',
            'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'sdtc': 'urn:hl7-org:sdtc'
        }

        # Register namespaces for output
        ET.register_namespace('', 'urn:hl7-org:v3')
        ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        ET.register_namespace('sdtc', 'urn:hl7-org:sdtc')

        # Parse XML
        tree = ET.parse(ccda_file)
        root = tree.getroot()

        # Step 1: Update patient demographics
        print_info("Updating patient demographics...")
        root = update_patient_demographics(root, patient_data, practice_data, namespaces)

        # Step 2: Update encounter dates
        print_info("Updating encounter dates...")
        root = update_encounter_dates(root, encounter_date, namespaces)

        # Step 3: Filter to keep only addon encounter
        root = filter_addon_encounter_only(root, namespaces)

        # Step 4: Convert all dates to yyyyMMdd format (CRITICAL - backend can't parse yyyyMMddHHmmss)
        root = convert_all_dates_to_yyyyMMdd(root, namespaces)

        # Step 5: Fix medications section code (change 10160-0 to 29549-3)
        root = fix_medications_section_code(root, namespaces)

        # Step 6: Add componentOf/encompassingEncounter section (REQUIRED!)
        root = add_component_of_section(root, encounter_date, patient_id, namespaces)

        # Step 7: Convert to string for UUID replacement
        xml_content = ET.tostring(root, encoding='unicode', method='xml')

        # Step 8: Build UUID mapping
        print_info("Building UUID mapping...")
        uuid_map = build_uuid_mapping(xml_content, patient_id)

        # Step 9: Replace UUIDs
        print_info("Replacing UUIDs with alphanumeric IDs...")
        xml_content = replace_uuids_in_xml(xml_content, uuid_map)

        # Step 10: Parse XML again to add ThetaRho identifiers (needs to be after UUID replacement)
        root = ET.fromstring(xml_content.encode('utf-8'))
        base_identifier = f"a-{practice_id}.E-{patient_id}-{patient_id}_addon"
        root = add_thetarho_identifiers_to_resources(root, base_identifier, practice_id, namespaces)

        # Step 11: Restructure Results section with list/item/table for lab observations
        # CRITICAL: Backend processProcedureResults() expects this specific format
        root = restructure_results_section_for_backend(root, namespaces)

        # Step 12: Transform table headers to match backend expectations (CRITICAL for resource creation!)
        # Backend parser reads narrative HTML tables, not structured entries
        root = transform_table_headers_for_backend(root, namespaces)

        # Step 13: Generate clinical composition section (Progress Notes)
        # Backend will parse this section and create a Composition resource
        root = generate_clinical_composition_section(root, namespaces)

        # Step 14: CRITICAL - Strip ALL newlines from entire document before serialization
        # MDHT backend parser can't handle newlines in cell content
        print_info("Stripping newlines from all text content...")
        def strip_newlines_recursive(element):
            """Recursively strip newlines from all text and tail in entire document"""
            if element.text:
                element.text = element.text.replace('\n', '').replace('\r', '')
            if element.tail:
                element.tail = element.tail.replace('\n', '').replace('\r', '')
            for child in element:
                strip_newlines_recursive(child)

        strip_newlines_recursive(root)
        print_success("Stripped newlines from entire document")

        # Step 15: Final conversion to string
        xml_content = ET.tostring(root, encoding='unicode', method='xml')

        return xml_content

    except ET.ParseError as e:
        print_error(f"XML parsing error: {e}")
        return None
    except Exception as e:
        print_error(f"XML processing error: {e}")
        import traceback
        traceback.print_exc()
        return None

def generate_clinical_composition_section(root, namespaces):
    """
    Generate a Progress Notes section that backend will parse as a Composition resource.

    Backend (CCDAUtilsService.java:227-235) creates Composition from sections with code 10164-2.
    This function creates a summary of the clinical encounter including:
    - Diagnoses/Conditions
    - Medications
    - Procedures
    - Lab Results

    The narrative is placed in a <section><text> element that backend extracts.
    """
    print_info("Generating clinical composition section...")

    # Extract encounter date from encompassingEncounter
    encounter_date = "Unknown date"
    encompassing = root.find('.//hl7:componentOf/hl7:encompassingEncounter/hl7:effectiveTime/hl7:low', namespaces)
    if encompassing is not None and encompassing.get('value'):
        date_str = encompassing.get('value')
        # Format as YYYY-MM-DD
        if len(date_str) >= 8:
            encounter_date = f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"

    # Build clinical narrative from existing sections
    narrative_parts = []
    narrative_parts.append('<div xmlns="http://www.w3.org/1999/xhtml">')
    narrative_parts.append(f'<h3>Clinical Encounter Summary</h3>')
    narrative_parts.append(f'<p><b>Date:</b> {encounter_date}</p>')

    # Extract medications from medication section
    med_section = None
    for section in root.findall('.//hl7:section', namespaces):
        code = section.find('hl7:code', namespaces)
        if code is not None and code.get('code') == '10183-2':  # Medications section
            med_section = section
            break

    if med_section is not None:
        narrative_parts.append('<h4>Medications</h4>')
        narrative_parts.append('<ul>')

        # Extract from table if present
        for row in med_section.findall('.//hl7:table/hl7:tbody/hl7:tr', namespaces):
            cells = row.findall('hl7:td', namespaces)
            if cells and len(cells) > 0:
                med_name = cells[0].text if cells[0].text else 'Unknown medication'
                narrative_parts.append(f'<li>{med_name}</li>')

        narrative_parts.append('</ul>')

    # Extract procedures from procedure section
    proc_section = None
    for section in root.findall('.//hl7:section', namespaces):
        code = section.find('hl7:code', namespaces)
        if code is not None and code.get('code') == '47519-4':  # Procedures section
            proc_section = section
            break

    if proc_section is not None:
        narrative_parts.append('<h4>Procedures</h4>')
        narrative_parts.append('<ul>')

        # Extract from table if present
        for row in proc_section.findall('.//hl7:table/hl7:tbody/hl7:tr', namespaces):
            cells = row.findall('hl7:td', namespaces)
            if cells and len(cells) > 0:
                proc_name = cells[0].text if cells[0].text else 'Unknown procedure'
                narrative_parts.append(f'<li>{proc_name}</li>')

        narrative_parts.append('</ul>')

    # Extract lab results from results section
    results_section = None
    for section in root.findall('.//hl7:section', namespaces):
        code = section.find('hl7:code', namespaces)
        if code is not None and code.get('code') == '30954-2':  # Results section
            results_section = section
            break

    if results_section is not None:
        narrative_parts.append('<h4>Laboratory Results</h4>')
        narrative_parts.append('<ul>')

        # Extract from captions
        for caption in results_section.findall('.//hl7:caption', namespaces):
            if caption.text:
                # Remove any tag prefixes we might have added
                caption_text = caption.text
                narrative_parts.append(f'<li>{caption_text}</li>')

        narrative_parts.append('</ul>')

    # Extract vital signs
    vitals_section = None
    for section in root.findall('.//hl7:section', namespaces):
        code = section.find('hl7:code', namespaces)
        if code is not None and code.get('code') == '8716-3':  # Vital signs section
            vitals_section = section
            break

    if vitals_section is not None:
        narrative_parts.append('<h4>Vital Signs</h4>')
        narrative_parts.append('<ul>')

        # Extract from table
        for row in vitals_section.findall('.//hl7:table/hl7:tbody/hl7:tr', namespaces):
            cells = row.findall('hl7:td', namespaces)
            if cells and len(cells) >= 2:
                vital_name = cells[0].text if cells[0].text else 'Unknown'
                vital_value = cells[1].text if cells[1].text else 'Unknown'
                narrative_parts.append(f'<li>{vital_name}: {vital_value}</li>')

        narrative_parts.append('</ul>')

    narrative_parts.append('</div>')

    # Create the Progress Notes section
    # Using section code 10164-2 which backend recognizes for Composition creation
    structured_body = root.find('.//hl7:structuredBody', namespaces)
    if structured_body is not None:
        # Create new section element
        section = ET.Element('{urn:hl7-org:v3}section')

        # Add templateId
        template_id = ET.SubElement(section, '{urn:hl7-org:v3}templateId')
        template_id.set('root', '2.16.840.1.113883.10.20.22.2.10')
        template_id.set('extension', '2014-06-09')

        # Add code element - 10164-2 is Progress Notes
        code = ET.SubElement(section, '{urn:hl7-org:v3}code')
        code.set('code', '10164-2')
        code.set('codeSystem', '2.16.840.1.113883.6.1')
        code.set('codeSystemName', 'LOINC')
        code.set('displayName', 'History of Present illness Narrative')

        # Add title
        title = ET.SubElement(section, '{urn:hl7-org:v3}title')
        title.text = 'Clinical Encounter Note'

        # Add text with narrative
        text = ET.SubElement(section, '{urn:hl7-org:v3}text')
        text.text = '\n'.join(narrative_parts)

        # Add section to structured body (at the end)
        component = ET.Element('{urn:hl7-org:v3}component')
        component.append(section)
        structured_body.append(component)

        print_success("Added clinical composition section (Progress Notes)")
    else:
        print_error("Could not find structuredBody element")

    return root

def save_final_xml(xml_content, patient_id):
    """
    Save processed XML to mock_patients folder
    """
    try:
        # Ensure mock_patients directory exists
        os.makedirs(MOCK_PATIENTS_DIR, exist_ok=True)

        # Output file path
        output_file = os.path.join(MOCK_PATIENTS_DIR, f"{patient_id}_addon.xml")

        # Write XML
        with open(output_file, 'w', encoding='utf-8') as f:
            # Add XML declaration
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write(xml_content)

        print_success(f"Saved addon CCDA: {output_file}")

        # Print file size
        file_size = os.path.getsize(output_file)
        print_info(f"File size: {file_size:,} bytes")

        return output_file

    except Exception as e:
        print_error(f"Failed to save XML file: {e}")
        return None

# ============================================================================
# Main Workflow
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description='Generate CCDA addon for existing patients',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_addon.py --patient-id t1210 --practice-id 11783 --server-url danvers-clone.thetarho.com
  python generate_addon.py --patient-id t1210 --practice-id 11783 --server-url localhost --encounter-date 2025-11-13
        """
    )

    parser.add_argument('--patient-id', required=True, help='Patient ID (e.g., t1210)')
    parser.add_argument('--practice-id', required=True, help='Practice ID (e.g., 11783 or a-11783)')
    parser.add_argument('--server-url', required=True, help='Base server URL without port (e.g., danvers-clone.thetarho.com)')
    parser.add_argument('--encounter-date',
                        default=(datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
                        help='Encounter date in YYYY-MM-DD format (default: 30 days ago, must be within last 6 months)')
    parser.add_argument('--output', help='Output file path (default: mock_patients/{patient_id}_addon.xml)')

    args = parser.parse_args()

    # Normalize practice ID (strip 'a-' prefix if present)
    practice_id = args.practice_id
    if practice_id.startswith('a-'):
        practice_id = practice_id[2:]  # Remove 'a-' prefix
    args.practice_id = practice_id

    # Validate encounter date is within last 6 months and not in future
    try:
        encounter_dt = datetime.strptime(args.encounter_date, '%Y-%m-%d')
        today = datetime.now()
        six_months_ago = today - timedelta(days=180)

        if encounter_dt > today:
            print_error(f"Encounter date cannot be in the future: {args.encounter_date}")
            print_error(f"Today is: {today.strftime('%Y-%m-%d')}")
            return 1

        if encounter_dt < six_months_ago:
            print_error(f"Encounter date must be within last 6 months: {args.encounter_date}")
            print_error(f"Earliest allowed date: {six_months_ago.strftime('%Y-%m-%d')}")
            return 1

    except ValueError as e:
        print_error(f"Invalid encounter date format: {args.encounter_date}")
        print_error("Expected format: YYYY-MM-DD (e.g., 2025-11-13)")
        return 1

    # Load LOINC component mappings from CSV file
    load_loinc_mappings()

    # Print header
    print_header("CCDA Addon Generator for ThetaRho Platform")

    print_info(f"Patient ID: {args.patient_id}")
    # Display effective FHIR URL based on server_url format
    if args.server_url.startswith('http://') or args.server_url.startswith('https://'):
        effective_fhir_url = args.server_url
    elif ':' in args.server_url:
        effective_fhir_url = f"http://{args.server_url}"
    else:
        effective_fhir_url = f"http://{args.server_url}:8080/fhir"

    print_info(f"Base Server URL: {args.server_url}")
    print_info(f"HAPI FHIR URL: {effective_fhir_url}")
    print_info(f"Encounter Date: {args.encounter_date}")
    print()

    # ========================================================================
    # Step 1: Move addon module to modules folder
    # ========================================================================
    print_step(1, "Moving addon module to modules folder")
    if not move_addon_to_modules():
        print_error("Failed to move addon module")
        return 1
    print()

    # ========================================================================
    # Step 2: Generate CCDA using Synthea
    # ========================================================================
    print_step(2, "Generating CCDA using Synthea")
    ccda_file = generate_synthea_ccda()
    if not ccda_file:
        cleanup_addon_from_modules()
        return 1
    print()

    # ========================================================================
    # Step 3: Fetch patient data from FHIR
    # ========================================================================
    print_step(3, "Fetching patient data from FHIR server")
    patient_data = fetch_patient_from_fhir(args.server_url, args.patient_id)
    if not patient_data:
        cleanup_addon_from_modules()
        return 1
    print()

    # ========================================================================
    # Step 4: Fetch organization data from patient's managing organization
    # ========================================================================
    print_step(4, "Fetching organization from patient's managing organization")
    organization_data = fetch_organization_from_fhir(args.server_url, patient_data)
    print()

    # ========================================================================
    # Step 5: Process CCDA XML
    # ========================================================================
    print_step(5, "Processing CCDA XML")
    print_info("  - Updating patient demographics")
    print_info("  - Updating encounter dates")
    print_info("  - Filtering addon encounter only")
    print_info("  - Adding componentOf/encompassingEncounter section")
    print_info("  - Replacing UUIDs with alphanumeric IDs")

    processed_xml = process_ccda_xml(ccda_file, patient_data, organization_data,
                                      args.patient_id, args.practice_id, args.encounter_date)
    if not processed_xml:
        cleanup_addon_from_modules()
        return 1
    print()

    # ========================================================================
    # Step 6: Save final XML
    # ========================================================================
    print_step(6, "Saving final addon CCDA")
    output_file = save_final_xml(processed_xml, args.patient_id)
    if not output_file:
        cleanup_addon_from_modules()
        return 1
    print()

    # ========================================================================
    # Step 7: Cleanup
    # ========================================================================
    print_step(7, "Cleaning up temporary files")
    cleanup_addon_from_modules()
    print()

    # ========================================================================
    # Final Summary
    # ========================================================================
    print_header("Generation Complete!")
    print_success(f"CCDA addon created: {output_file}")
    print()
    print_info("Next steps:")
    print_info(f"  1. Review the generated XML: {output_file}")
    print_info(f"  2. Upload addon to patient:")
    print_info(f"     ./scripts/upload_addon_ccda.sh {args.patient_id} {args.practice_id} {output_file} {args.server_url}")
    print()
    print_info(f"Full command: ./scripts/upload_addon_ccda.sh {args.patient_id} {args.practice_id} {output_file} {args.server_url}")
    print()

    return 0

if __name__ == '__main__':
    sys.exit(main())

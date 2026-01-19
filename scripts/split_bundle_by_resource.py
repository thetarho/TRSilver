#!/usr/bin/env python3
"""
Split FHIR transaction bundle into separate files by resource type.

This script takes a FHIR bundle and creates individual JSON files for each resource type,
suitable for uploading to HAPI FHIR server and triggering aggregator map population.

Supported Resource Types (40+ FHIR resources):

Clinical Resources:
- {patient_id}Patient.json          - Patient demographic data
- {patient_id}Condition.json        - Diagnoses and health conditions
- {patient_id}Procedure.json        - Surgical and medical procedures
- {patient_id}Observations.json     - Vital signs, labs, social history
- {patient_id}DiagnosticReport.json - Lab reports, imaging reports
- {patient_id}ImagingStudy.json     - Radiology studies (X-ray, CT, MRI)
- {patient_id}Media.json            - Medical images and attachments
- {patient_id}Specimen.json         - Lab specimens

Medications & Allergies:
- {patient_id}Medication.json       - Medication definitions
- {patient_id}MedicationRequests.json - Prescriptions and medication orders
- {patient_id}MedicationStatements.json - Patient medication history
- {patient_id}MedicationAdministration.json - Administered medications
- {patient_id}Immunization.json     - Vaccination records
- {patient_id}AllergyIntolerance.json - Drug allergies and intolerances

Care Planning:
- {patient_id}CarePlan.json         - Care plans and treatment plans
- {patient_id}CareTeam.json         - Care team members and roles
- {patient_id}Goal.json             - Patient health goals
- {patient_id}ServiceRequest.json   - Orders for procedures, labs, imaging
- {patient_id}Task.json             - Clinical workflow tasks

Encounters & Episodes:
- {patient_id}Encounters.json       - Office visits, hospitalizations
- {patient_id}EpisodeOfCare.json    - Episodes of care
- {patient_id}Appointment.json      - Scheduled appointments

Documents:
- {patient_id}DocumentReference.json - Clinical documents and CCDAs
- {patient_id}Composition.json      - Clinical notes composition

Providers & Organizations:
- {patient_id}Practitioner.json     - Healthcare providers
- {patient_id}PractitionerRole.json - Provider roles and specialties
- {patient_id}Organization.json     - Healthcare organizations
- {patient_id}Location.json         - Facilities and locations
- {patient_id}HealthcareService.json - Healthcare services offered

Financial:
- {patient_id}Claim.json            - Insurance claims
- {patient_id}ExplanationOfBenefit.json - EOB documents
- {patient_id}Coverage.json         - Insurance coverage

Devices:
- {patient_id}Device.json           - Medical devices and implants
- {patient_id}DeviceRequest.json    - Device orders
- {patient_id}DeviceUseStatement.json - Device usage records

Family & Social:
- {patient_id}FamilyMemberHistory.json - Family health history
- {patient_id}RelatedPerson.json    - Emergency contacts, caregivers

Additional Clinical:
- {patient_id}ClinicalImpression.json - Clinical assessments
- {patient_id}DetectedIssue.json    - Clinical alerts and warnings
- {patient_id}RiskAssessment.json   - Risk scores and assessments

Data & Provenance:
- {patient_id}Binary.json           - Binary data (PDFs, images)
- {patient_id}Provenance.json       - Data provenance and audit trails
- {patient_id}AuditEvent.json       - Security audit events

All output files are FHIR transaction bundles ready for upload to HAPI FHIR server.
When uploaded via FHIR API, the server will automatically populate aggregator maps.

Usage:
    # Split Synthea-generated bundle
    python3 split_bundle_by_resource.py \\
        --input ../chatty-notes/output/athena_patient_995000.json \\
        --output mock_patients/995000/

    # Split existing bundle
    python3 split_bundle_by_resource.py \\
        --input output/fhir/bundle.json \\
        --output mock_patients/patient_new/
"""

import json
import argparse
import os
from typing import Dict, List, Any
from collections import defaultdict


def create_resource_bundle(resources: List[Dict[str, Any]], bundle_type: str = "collection") -> Dict[str, Any]:
    """
    Create a FHIR bundle from a list of resources.

    Args:
        resources: List of FHIR resources
        bundle_type: Type of bundle (collection, transaction, etc.)

    Returns:
        FHIR bundle containing the resources
    """
    entries = []
    for resource in resources:
        entry = {"resource": resource}

        # For transaction bundles, add request information for PUT operations
        if bundle_type == "transaction":
            resource_type = resource.get('resourceType')
            resource_id = resource.get('id')
            if resource_type and resource_id:
                entry["request"] = {
                    "method": "PUT",
                    "url": f"{resource_type}/{resource_id}"
                }

        entries.append(entry)

    return {
        "resourceType": "Bundle",
        "type": bundle_type,
        "entry": entries
    }


def split_bundle_by_resource(input_file: str, output_dir: str) -> None:
    """
    Split FHIR bundle into separate files by resource type.

    Args:
        input_file: Path to input FHIR bundle
        output_dir: Directory for output files
    """
    print(f"\n{'='*70}")
    print(f"Splitting FHIR Bundle by Resource Type")
    print(f"{'='*70}")
    print(f"Input:  {input_file}")
    print(f"Output: {output_dir}")

    # Load bundle
    print("\nLoading FHIR bundle...")
    with open(input_file, 'r') as f:
        bundle = json.load(f)

    entry_count = len(bundle.get('entry', []))
    print(f"Loaded bundle with {entry_count} entries")

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Group resources by type
    print("\nGrouping resources by type...")
    resources_by_type = defaultdict(list)
    patient_id = None

    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')

        if not resource_type:
            continue

        resources_by_type[resource_type].append(resource)

        # Get patient ID for file naming
        if resource_type == 'Patient' and patient_id is None:
            patient_id = resource.get('id')

    # Print summary
    print(f"\nFound resources:")
    for resource_type, resources in sorted(resources_by_type.items()):
        print(f"  {resource_type}: {len(resources)}")

    if not patient_id:
        print("\nWARNING: No Patient resource found, using 'unknown' for file names")
        patient_id = 'unknown'

    print(f"\nPatient ID: {patient_id}")

    # Write separate files for each resource type
    print(f"\nWriting resource files to {output_dir}...")

    files_created = []

    # Patient resource as transaction bundle (consistent with other shared resources)
    if 'Patient' in resources_by_type:
        patient_file = os.path.join(output_dir, f"{patient_id}Patient.json")
        # Create transaction bundle for Patient (allows upload via web UI)
        patient_bundle = create_resource_bundle(resources_by_type['Patient'], bundle_type="transaction")
        with open(patient_file, 'w') as f:
            json.dump(patient_bundle, f, indent=2)
        files_created.append(patient_file)
        print(f"  ✓ {patient_id}Patient.json (1 resource in transaction bundle)")

    # Resource type to file name mapping (plurals and special cases)
    # Organized by category for clarity
    resource_file_names = {
        # Clinical Resources
        'Condition': 'Condition',
        'Procedure': 'Procedure',
        'Observation': 'Observations',
        'DiagnosticReport': 'DiagnosticReport',
        'ImagingStudy': 'ImagingStudy',
        'Media': 'Media',
        'Specimen': 'Specimen',

        # Medications & Allergies
        'Medication': 'Medication',
        'MedicationRequest': 'MedicationRequests',
        'MedicationStatement': 'MedicationStatements',
        'MedicationAdministration': 'MedicationAdministration',
        'Immunization': 'Immunization',
        'AllergyIntolerance': 'AllergyIntolerance',

        # Care Planning
        'CarePlan': 'CarePlan',
        'CareTeam': 'CareTeam',
        'Goal': 'Goal',
        'ServiceRequest': 'ServiceRequest',
        'Task': 'Task',

        # Encounters & Episodes
        'Encounter': 'Encounters',
        'EpisodeOfCare': 'EpisodeOfCare',
        'Appointment': 'Appointment',

        # Documents & References
        'DocumentReference': 'DocumentReference',
        'DiagnosticReport': 'DiagnosticReport',
        'Composition': 'Composition',

        # Providers & Organizations
        'Practitioner': 'Practitioner',
        'PractitionerRole': 'PractitionerRole',
        'Organization': 'Organization',
        'Location': 'Location',
        'HealthcareService': 'HealthcareService',

        # Financial
        'Claim': 'Claim',
        'ExplanationOfBenefit': 'ExplanationOfBenefit',
        'Coverage': 'Coverage',

        # Devices
        'Device': 'Device',
        'DeviceRequest': 'DeviceRequest',
        'DeviceUseStatement': 'DeviceUseStatement',

        # Family & Social
        'FamilyMemberHistory': 'FamilyMemberHistory',
        'RelatedPerson': 'RelatedPerson',

        # Additional Clinical
        'ClinicalImpression': 'ClinicalImpression',
        'DetectedIssue': 'DetectedIssue',
        'RiskAssessment': 'RiskAssessment',

        # Data & Provenance
        'Binary': 'Binary',
        'Provenance': 'Provenance',
        'AuditEvent': 'AuditEvent',
    }

    # Write bundles for other resource types
    for resource_type, file_name_suffix in resource_file_names.items():
        if resource_type in resources_by_type and resource_type != 'Patient':
            resources = resources_by_type[resource_type]
            output_file = os.path.join(output_dir, f"{patient_id}{file_name_suffix}.json")

            # Create bundle
            # Use "transaction" bundle type for FHIR server uploads
            resource_bundle = create_resource_bundle(resources, bundle_type="transaction")

            with open(output_file, 'w') as f:
                json.dump(resource_bundle, f, indent=2)

            files_created.append(output_file)
            print(f"  ✓ {patient_id}{file_name_suffix}.json ({len(resources)} resources)")

    # Summary
    print(f"\n{'='*70}")
    print(f"Split complete!")
    print(f"{'='*70}")
    print(f"\nCreated {len(files_created)} files in {output_dir}/")
    print(f"\nFiles created:")
    for file in sorted(files_created):
        file_size = os.path.getsize(file)
        print(f"  {os.path.basename(file):<40} ({file_size:>8,} bytes)")

    print(f"\nNext steps:")
    print(f"1. Validate format: python3 scripts/validate_athena_format.py --input {output_dir}")
    print(f"2. Load to FHIR store (all files are transaction bundles, upload via web UI or curl):")
    print(f"   curl -X POST http://localhost:8080/fhir -H 'Content-Type: application/fhir+json' -d @{output_dir}/{patient_id}Patient.json")
    print(f"3. Index patient: curl -X POST http://localhost:9090/athenahealth/indexPatient/{patient_id}")


def main():
    parser = argparse.ArgumentParser(
        description='Split FHIR bundle into separate files by resource type',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Split bundle into resource files
  python3 split_bundle_by_resource.py \\
    --input ../chatty-notes/output/athena_patient_995000.json \\
    --output 995000/

  # Alternative with explicit paths
  python3 split_bundle_by_resource.py \\
    --input output/fhir/athena_patient_995000.json \\
    --output mock_patients/995000/
        """
    )

    parser.add_argument('--input', required=True, help='Input FHIR bundle file')
    parser.add_argument('--output', required=True, help='Output directory for resource files')

    args = parser.parse_args()

    split_bundle_by_resource(
        input_file=args.input,
        output_dir=args.output
    )


if __name__ == '__main__':
    main()

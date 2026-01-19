#!/usr/bin/env python3
"""
ThetaRho Patient Bundle Validator

This script performs comprehensive validation of FHIR patient bundles against
ThetaRho service requirements including:
- FhirDataValidationQueryService.java (ThetaRhoAppServer)
- FhirQueryService.java (ThetaRhoAppServer)
- PatientTaggingService.java (TRDataServices)
- TRAIS AI service requirements

Usage:
    python3 validate_patient.py --input <bundle_file>
    python3 validate_patient.py --input patient_bundle.json --verbose
    python3 validate_patient.py --input patient_bundle.json --output report.md

Exit codes:
    0 - All validations passed
    1 - Critical issues found
    2 - File/parsing errors
"""

import json
import sys
import argparse
from typing import Dict, List, Any, Tuple, Optional
from collections import defaultdict
from datetime import datetime
import os


class ValidationResult:
    """Stores validation results for a specific check"""

    def __init__(self, check_name: str, service: str, line_ref: str = ""):
        self.check_name = check_name
        self.service = service
        self.line_ref = line_ref
        self.passed = True
        self.issues: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
        self.resource_count = 0
        self.validated_count = 0

    def add_issue(self, message: str):
        """Add a critical issue"""
        self.issues.append(message)
        self.passed = False

    def add_warning(self, message: str):
        """Add a warning (non-critical)"""
        self.warnings.append(message)

    def add_info(self, message: str):
        """Add informational message"""
        self.info.append(message)

    def __str__(self) -> str:
        status = "✅ PASS" if self.passed else "❌ FAIL"
        ref = f" ({self.line_ref})" if self.line_ref else ""
        count = f" [{self.validated_count}/{self.resource_count}]" if self.resource_count > 0 else ""
        return f"{status}: {self.check_name}{ref}{count}"


class PatientBundleValidator:
    """Validates FHIR patient bundles against ThetaRho service requirements"""

    # Expected resource types for a complete patient
    EXPECTED_RESOURCES = {
        'Patient': {'required': True, 'min_count': 1, 'max_count': 1},
        'AllergyIntolerance': {'required': False, 'min_count': 0},
        'Condition': {'required': False, 'min_count': 0},
        'MedicationRequest': {'required': False, 'min_count': 0},
        'MedicationAdministration': {'required': False, 'min_count': 0},
        'Immunization': {'required': False, 'min_count': 0},
        'Observation': {'required': False, 'min_count': 0},
        'DiagnosticReport': {'required': False, 'min_count': 0},
        'Procedure': {'required': False, 'min_count': 0},
        'Encounter': {'required': False, 'min_count': 0},
        'Composition': {'required': False, 'min_count': 0},
        'DocumentReference': {'required': False, 'min_count': 0},
    }

    # DiagnosticReport subtypes
    DR_SUBTYPES = {
        'drCBC': 'Complete Blood Count',
        'drCMP': 'Comprehensive Metabolic Panel',
        'drBMP': 'Basic Metabolic Panel',
        'drLP': 'Lipid Panel',
        'drHBA1C': 'Hemoglobin A1C',
        'drUA': 'Urinalysis',
        'drOTHER': 'Other Diagnostic Report'
    }

    def __init__(self, bundle_path: str, verbose: bool = False):
        self.bundle_path = bundle_path
        self.verbose = verbose
        self.bundle: Dict[str, Any] = {}
        self.resources_by_type: Dict[str, List[Dict]] = defaultdict(list)
        self.results: List[ValidationResult] = []
        self.critical_issues: List[str] = []
        self.warnings: List[str] = []

    def load_bundle(self) -> bool:
        """Load and parse the FHIR bundle"""
        try:
            with open(self.bundle_path, 'r', encoding='utf-8') as f:
                self.bundle = json.load(f)

            # Organize resources by type
            for entry in self.bundle.get('entry', []):
                resource = entry.get('resource', {})
                resource_type = resource.get('resourceType')
                if resource_type:
                    self.resources_by_type[resource_type].append(resource)

            return True
        except FileNotFoundError:
            print(f"❌ ERROR: File not found: {self.bundle_path}", file=sys.stderr)
            return False
        except json.JSONDecodeError as e:
            print(f"❌ ERROR: Invalid JSON: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"❌ ERROR: Failed to load bundle: {e}", file=sys.stderr)
            return False

    def validate_bundle_structure(self) -> ValidationResult:
        """Validate basic bundle structure"""
        result = ValidationResult(
            "Bundle Structure",
            "FHIR R4 Specification"
        )

        if not isinstance(self.bundle, dict):
            result.add_issue("Bundle is not a JSON object")
            return result

        if self.bundle.get('resourceType') != 'Bundle':
            result.add_issue(f"Invalid resourceType: {self.bundle.get('resourceType')}, expected 'Bundle'")

        if 'entry' not in self.bundle:
            result.add_issue("Bundle missing 'entry' array")
        elif not isinstance(self.bundle['entry'], list):
            result.add_issue("Bundle 'entry' is not an array")

        entry_count = len(self.bundle.get('entry', []))
        if entry_count == 0:
            result.add_warning("Bundle is empty")
        else:
            result.add_info(f"Bundle contains {entry_count} entries")

        return result

    def validate_resource_inventory(self) -> ValidationResult:
        """Validate presence of expected resource types"""
        result = ValidationResult(
            "Resource Inventory",
            "ThetaRho Service Requirements"
        )

        for resource_type, requirements in self.EXPECTED_RESOURCES.items():
            count = len(self.resources_by_type.get(resource_type, []))

            if requirements['required'] and count == 0:
                result.add_issue(f"Required resource type '{resource_type}' is missing")

            if 'min_count' in requirements and count < requirements['min_count']:
                result.add_warning(f"{resource_type}: {count} found, minimum {requirements['min_count']} expected")

            if 'max_count' in requirements and count > requirements['max_count']:
                result.add_warning(f"{resource_type}: {count} found, maximum {requirements['max_count']} expected")

            if count > 0:
                result.add_info(f"{resource_type}: {count}")

        # Check for unexpected resource types
        expected_types = set(self.EXPECTED_RESOURCES.keys())
        # Add supporting resources that are okay to have
        expected_types.update(['Organization', 'Practitioner', 'Location', 'Medication',
                               'Claim', 'ExplanationOfBenefit', 'Provenance', 'PractitionerRole'])

        for resource_type in self.resources_by_type.keys():
            if resource_type not in expected_types:
                result.add_info(f"Additional resource type: {resource_type} ({len(self.resources_by_type[resource_type])})")

        return result

    def validate_medication_request(self) -> ValidationResult:
        """
        Validate MedicationRequest resources

        Critical: FhirQueryService.java:3383
        String display = ((Reference) medication).getDisplay();

        Must have medicationReference with display field, NOT medicationCodeableConcept
        """
        result = ValidationResult(
            "MedicationRequest.medication",
            "FhirQueryService.java",
            "Line 3383"
        )

        resources = self.resources_by_type.get('MedicationRequest', [])
        result.resource_count = len(resources)

        if result.resource_count == 0:
            result.add_info("No MedicationRequest resources in bundle")
            return result

        for resource in resources:
            res_id = resource.get('id', 'unknown')

            # Check for medicationCodeableConcept (wrong format)
            if 'medicationCodeableConcept' in resource:
                result.add_issue(
                    f"MedicationRequest/{res_id}: Uses medicationCodeableConcept "
                    "(causes ClassCastException). Must use medicationReference with display."
                )
                continue

            # Check for medicationReference
            if 'medicationReference' not in resource:
                result.add_issue(
                    f"MedicationRequest/{res_id}: Missing medication field. "
                    "Must have medicationReference with display."
                )
                continue

            med_ref = resource['medicationReference']

            # Check for display field
            if 'display' not in med_ref or not med_ref['display']:
                result.add_issue(
                    f"MedicationRequest/{res_id}: medicationReference missing display field. "
                    "Service expects ((Reference) medication).getDisplay()."
                )
            else:
                result.validated_count += 1
                if self.verbose:
                    result.add_info(f"MedicationRequest/{res_id}: display = '{med_ref['display'][:50]}...'")

        if result.validated_count == result.resource_count:
            result.passed = True

        return result

    def validate_encounter_service_provider(self) -> ValidationResult:
        """
        Validate Encounter.serviceProvider has display field

        FhirQueryService.java:2338-2343
        String display = serviceProvider.getDisplay();
        retVal.addHospitals(display);
        """
        result = ValidationResult(
            "Encounter.serviceProvider.display",
            "FhirQueryService.java",
            "Line 2340"
        )

        resources = self.resources_by_type.get('Encounter', [])
        result.resource_count = len(resources)

        if result.resource_count == 0:
            result.add_info("No Encounter resources in bundle")
            return result

        for resource in resources:
            res_id = resource.get('id', 'unknown')

            if 'serviceProvider' not in resource:
                result.add_warning(f"Encounter/{res_id}: No serviceProvider (hospital name won't display)")
                continue

            sp = resource['serviceProvider']

            if 'display' not in sp or not sp['display']:
                result.add_issue(
                    f"Encounter/{res_id}: serviceProvider missing display field. "
                    "Hospital name won't appear in ER/UrgentCare sections."
                )
            else:
                result.validated_count += 1
                if self.verbose:
                    result.add_info(f"Encounter/{res_id}: serviceProvider = '{sp['display']}'")

        if result.validated_count == result.resource_count:
            result.passed = True

        return result

    def validate_allergy_intolerance(self) -> ValidationResult:
        """
        Validate AllergyIntolerance CodeableConcept text fields

        FhirDataValidationQueryService.java:319, 324, 333
        boolean active = clinicalStatus.getText().equalsIgnoreCase(ACTIVE);
        boolean confirmed = verificationStatus.getText().equalsIgnoreCase(CONFIRMED);
        allergyText = codeableConcept.getText();
        """
        result = ValidationResult(
            "AllergyIntolerance text fields",
            "FhirDataValidationQueryService.java",
            "Lines 319, 324, 333"
        )

        resources = self.resources_by_type.get('AllergyIntolerance', [])
        result.resource_count = len(resources)

        if result.resource_count == 0:
            result.add_info("No AllergyIntolerance resources in bundle")
            return result

        for resource in resources:
            res_id = resource.get('id', 'unknown')
            issues_found = []

            # Check clinicalStatus.text
            cs = resource.get('clinicalStatus', {})
            if 'text' not in cs or not cs['text']:
                issues_found.append("clinicalStatus.text missing")

            # Check verificationStatus.text
            vs = resource.get('verificationStatus', {})
            if 'text' not in vs or not vs['text']:
                issues_found.append("verificationStatus.text missing")

            # Check code.text
            code = resource.get('code', {})
            if 'text' not in code or not code['text']:
                issues_found.append("code.text missing")

            if issues_found:
                result.add_issue(
                    f"AllergyIntolerance/{res_id}: {', '.join(issues_found)}. "
                    "Causes NullPointerException in validation service."
                )
            else:
                result.validated_count += 1

        if result.validated_count == result.resource_count:
            result.passed = True

        return result

    def validate_condition(self) -> ValidationResult:
        """
        Validate Condition CodeableConcept text fields

        FhirDataValidationQueryService.java:489, 494, 501
        boolean active = clinicalStatus.getText().equalsIgnoreCase(ACTIVE);
        boolean confirmed = verificationStatus.getText().equalsIgnoreCase(CONFIRMED);
        description = codeableConcept.getText();
        """
        result = ValidationResult(
            "Condition text fields",
            "FhirDataValidationQueryService.java",
            "Lines 489, 494, 501"
        )

        resources = self.resources_by_type.get('Condition', [])
        result.resource_count = len(resources)

        if result.resource_count == 0:
            result.add_info("No Condition resources in bundle")
            return result

        for resource in resources:
            res_id = resource.get('id', 'unknown')
            issues_found = []

            # Check clinicalStatus.text
            cs = resource.get('clinicalStatus', {})
            if 'text' not in cs or not cs['text']:
                issues_found.append("clinicalStatus.text missing")

            # Check verificationStatus.text
            vs = resource.get('verificationStatus', {})
            if 'text' not in vs or not vs['text']:
                issues_found.append("verificationStatus.text missing")

            # Check code.text (optional but recommended)
            code = resource.get('code', {})
            if 'text' not in code or not code['text']:
                issues_found.append("code.text missing")

            if issues_found:
                result.add_issue(
                    f"Condition/{res_id}: {', '.join(issues_found)}. "
                    "Causes NullPointerException in validation service."
                )
            else:
                result.validated_count += 1

        if result.validated_count == result.resource_count:
            result.passed = True

        return result

    def validate_immunization(self) -> ValidationResult:
        """
        Validate Immunization.vaccineCode.text

        FhirDataValidationQueryService.java:415
        description = vaccineCode.getText();
        """
        result = ValidationResult(
            "Immunization.vaccineCode.text",
            "FhirDataValidationQueryService.java",
            "Line 415"
        )

        resources = self.resources_by_type.get('Immunization', [])
        result.resource_count = len(resources)

        if result.resource_count == 0:
            result.add_info("No Immunization resources in bundle")
            return result

        for resource in resources:
            res_id = resource.get('id', 'unknown')

            vc = resource.get('vaccineCode', {})
            if 'text' not in vc or not vc['text']:
                result.add_warning(
                    f"Immunization/{res_id}: vaccineCode.text missing "
                    "(has coding fallback, but text preferred)"
                )
            else:
                result.validated_count += 1

        if result.validated_count == result.resource_count:
            result.passed = True
        elif result.validated_count > 0:
            result.passed = True  # Warnings only

        return result

    def validate_observation(self) -> ValidationResult:
        """
        Validate Observation.code.text

        FhirQueryService.java:3635-3639
        String text = codeableConcept.getText();
        if (text == null || text.isEmpty()) {
            text = codeableConcept.getCodingFirstRep().getDisplay();
        }
        """
        result = ValidationResult(
            "Observation.code.text",
            "FhirQueryService.java",
            "Lines 3635-3639"
        )

        resources = self.resources_by_type.get('Observation', [])
        result.resource_count = len(resources)

        if result.resource_count == 0:
            result.add_info("No Observation resources in bundle")
            return result

        for resource in resources:
            res_id = resource.get('id', 'unknown')

            code = resource.get('code', {})
            if 'text' not in code or not code['text']:
                result.add_warning(
                    f"Observation/{res_id}: code.text missing "
                    "(has coding fallback, but text preferred)"
                )
            else:
                result.validated_count += 1

        if result.validated_count == result.resource_count:
            result.passed = True
        elif result.validated_count > 0:
            result.passed = True  # Warnings only

        return result

    def validate_diagnostic_report(self) -> ValidationResult:
        """
        Validate DiagnosticReport.code.text and dr_subtype meta tags

        FhirDataValidationQueryService.java:1262-1265, 1292-1294
        if (coding.getCode() != null && coding.getCode().startsWith("dr_subtype:"))
        details.append(codeableConcept.getText());
        """
        result = ValidationResult(
            "DiagnosticReport validation",
            "FhirDataValidationQueryService.java",
            "Lines 1262-1265, 1292-1294"
        )

        resources = self.resources_by_type.get('DiagnosticReport', [])
        result.resource_count = len(resources)

        if result.resource_count == 0:
            result.add_info("No DiagnosticReport resources in bundle")
            return result

        subtype_counts = defaultdict(int)

        for resource in resources:
            res_id = resource.get('id', 'unknown')
            issues_found = []

            # Check code.text
            code = resource.get('code', {})
            if 'text' not in code or not code['text']:
                issues_found.append("code.text missing")

            # Check dr_subtype meta tag
            meta = resource.get('meta', {})
            tags = meta.get('tag', [])

            has_subtype = False
            subtype_value = None

            for tag in tags:
                tag_code = tag.get('code', '')
                if tag_code.startswith('dr_subtype:'):
                    has_subtype = True
                    subtype_value = tag_code.split(':', 1)[1]
                    subtype_counts[subtype_value] += 1
                    break

            if not has_subtype:
                issues_found.append("dr_subtype meta tag missing (required for TRAIS AI)")

            if issues_found:
                result.add_issue(f"DiagnosticReport/{res_id}: {', '.join(issues_found)}")
            else:
                result.validated_count += 1
                if self.verbose and subtype_value:
                    result.add_info(f"DiagnosticReport/{res_id}: dr_subtype = {subtype_value}")

        # Add subtype distribution info
        if subtype_counts:
            result.add_info(f"dr_subtype distribution: {dict(subtype_counts)}")

        if result.validated_count == result.resource_count:
            result.passed = True

        return result

    def validate_procedure(self) -> ValidationResult:
        """
        Validate Procedure.code.text

        FhirQueryService.java:4070-4074
        String text = codeableConcept.getText();
        if (text == null || text.isEmpty()) {
            text = codeableConcept.getCodingFirstRep().getDisplay();
        }
        """
        result = ValidationResult(
            "Procedure.code.text",
            "FhirQueryService.java",
            "Lines 4070-4074"
        )

        resources = self.resources_by_type.get('Procedure', [])
        result.resource_count = len(resources)

        if result.resource_count == 0:
            result.add_info("No Procedure resources in bundle")
            return result

        for resource in resources:
            res_id = resource.get('id', 'unknown')

            code = resource.get('code', {})
            if 'text' not in code or not code['text']:
                result.add_warning(
                    f"Procedure/{res_id}: code.text missing "
                    "(has coding fallback, but text preferred)"
                )
            else:
                result.validated_count += 1

        if result.validated_count == result.resource_count:
            result.passed = True
        elif result.validated_count > 0:
            result.passed = True  # Warnings only

        return result

    def validate_medication_administration(self) -> ValidationResult:
        """
        Validate MedicationAdministration.medicationCodeableConcept.text

        FhirQueryService.java:3502
        String medicationText = medicationAdministration.getMedicationCodeableConcept().getText();
        """
        result = ValidationResult(
            "MedicationAdministration.medication",
            "FhirQueryService.java",
            "Line 3502"
        )

        resources = self.resources_by_type.get('MedicationAdministration', [])
        result.resource_count = len(resources)

        if result.resource_count == 0:
            result.add_info("No MedicationAdministration resources in bundle")
            return result

        for resource in resources:
            res_id = resource.get('id', 'unknown')

            if 'medicationCodeableConcept' in resource:
                mcc = resource['medicationCodeableConcept']
                if 'text' not in mcc or not mcc['text']:
                    result.add_issue(
                        f"MedicationAdministration/{res_id}: "
                        "medicationCodeableConcept.text missing"
                    )
                else:
                    result.validated_count += 1
            else:
                result.add_warning(
                    f"MedicationAdministration/{res_id}: "
                    "No medicationCodeableConcept found"
                )

        if result.validated_count == result.resource_count:
            result.passed = True

        return result

    def validate_patient_tagging_requirements(self) -> ValidationResult:
        """
        Validate resources required by PatientTaggingService.java

        TRDataServices PatientTaggingService requires these resource types:
        - Appointments (Encounter)
        - Vitals (Observation with category=vital-signs)
        - AllergyIntolerance
        - Immunization
        - Condition
        - MedicationRequest
        - DiagnosticReport
        - Encounter
        - Compositions (DocumentReference)
        - Procedure
        - NonVitals (Observation)
        """
        result = ValidationResult(
            "PatientTaggingService requirements",
            "PatientTaggingService.java (TRDataServices)",
            "Lines 34-46"
        )

        tagging_requirements = {
            'Encounter': 'Appointments and Encounters',
            'Observation': 'Vitals and NonVitals',
            'AllergyIntolerance': 'AllergyIntolerance',
            'Immunization': 'Immunization',
            'Condition': 'Condition',
            'MedicationRequest': 'MedicationRequest and Ontology',
            'DiagnosticReport': 'DiagnosticReports',
            'DocumentReference': 'Compositions',
            'Procedure': 'Procedures'
        }

        missing_types = []
        present_types = []

        for resource_type, description in tagging_requirements.items():
            count = len(self.resources_by_type.get(resource_type, []))
            if count == 0:
                missing_types.append(resource_type)
                result.add_warning(
                    f"No {resource_type} resources found (tagging task '{description}' will be skipped)"
                )
            else:
                present_types.append(f"{resource_type}({count})")
                result.validated_count += 1

        result.resource_count = len(tagging_requirements)

        if present_types:
            result.add_info(f"Present resource types: {', '.join(present_types)}")

        # Not critical if some are missing, so pass if any are present
        if result.validated_count > 0:
            result.passed = True
        else:
            result.add_issue("No taggable resource types found in bundle")

        return result

    def validate_medication_resources(self) -> ValidationResult:
        """
        Validate that all referenced Medication resources exist in bundle

        Critical: Ensures medicationReference in MedicationRequest points to existing Medication
        Prevents HAPI FHIR upload error: "Resource Medication/xxx not found"
        """
        result = ValidationResult(
            "Medication resource references",
            "HAPI FHIR Bundle Upload"
        )

        # Build map of all Medication resources in bundle
        medication_ids = set()
        medications = self.resources_by_type.get('Medication', [])

        for med in medications:
            med_id = med.get('id')
            if med_id:
                # Add all possible reference formats
                medication_ids.add(med_id)
                medication_ids.add(f'Medication/{med_id}')
                medication_ids.add(f'urn:uuid:{med_id}')

        result.add_info(f"Found {len(medications)} Medication resources in bundle")

        # Check all MedicationRequest references
        med_requests = self.resources_by_type.get('MedicationRequest', [])
        result.resource_count = len(med_requests)

        if result.resource_count == 0:
            result.add_info("No MedicationRequest resources to validate")
            result.passed = True
            return result

        missing_meds = []

        for mr in med_requests:
            mr_id = mr.get('id', 'unknown')
            med_ref = mr.get('medicationReference', {})
            ref = med_ref.get('reference')

            if not ref:
                result.add_issue(
                    f"MedicationRequest/{mr_id}: medicationReference has no reference field"
                )
                continue

            # Check if referenced Medication exists
            if ref not in medication_ids:
                missing_meds.append((mr_id, ref))
                result.add_issue(
                    f"MedicationRequest/{mr_id}: References {ref} which doesn't exist in bundle. "
                    "HAPI upload will fail!"
                )
            else:
                result.validated_count += 1

        if missing_meds:
            result.add_info(
                f"Missing {len(missing_meds)} Medication resources. "
                "Run convert_to_athena_format.py to create them."
            )

        if result.validated_count == result.resource_count:
            result.passed = True

        return result

    def validate_bundle_dependency_order(self) -> ValidationResult:
        """
        Validate bundle entry order for HAPI FHIR PUT requests

        Critical: Referenced resources must appear BEFORE resources that reference them
        Examples:
        - Medication before MedicationRequest
        - Patient before all patient-linked resources
        - Organization before resources referencing organizations
        """
        result = ValidationResult(
            "Bundle dependency order",
            "HAPI FHIR Bundle Upload"
        )

        entries = self.bundle.get('entry', [])
        if not entries:
            result.add_info("Bundle is empty")
            result.passed = True
            return result

        # Track resource positions
        resource_positions = {}
        for idx, entry in enumerate(entries):
            resource = entry.get('resource', {})
            res_type = resource.get('resourceType')
            res_id = resource.get('id')
            if res_type and res_id:
                key = f"{res_type}/{res_id}"
                resource_positions[key] = idx

        # Check critical dependencies
        dependencies = {
            'Medication': ['MedicationRequest', 'MedicationAdministration'],
            'Patient': ['Encounter', 'Observation', 'Condition', 'AllergyIntolerance',
                       'MedicationRequest', 'DiagnosticReport', 'Procedure', 'Immunization'],
            'Organization': ['Encounter', 'OrganizationAffiliation'],
            'Practitioner': ['Encounter', 'PractitionerRole'],
            'Location': ['Encounter']
        }

        order_issues = []

        for dependency_type, dependent_types in dependencies.items():
            # Get max position of dependency resources
            dep_resources = self.resources_by_type.get(dependency_type, [])
            if not dep_resources:
                continue

            dep_positions = []
            for dep_res in dep_resources:
                dep_id = dep_res.get('id')
                if dep_id:
                    key = f"{dependency_type}/{dep_id}"
                    if key in resource_positions:
                        dep_positions.append(resource_positions[key])

            if not dep_positions:
                continue

            max_dep_position = max(dep_positions)

            # Check that dependent resources come after
            for dependent_type in dependent_types:
                dep_type_resources = self.resources_by_type.get(dependent_type, [])
                for dep_type_res in dep_type_resources:
                    dep_type_id = dep_type_res.get('id')
                    if dep_type_id:
                        key = f"{dependent_type}/{dep_type_id}"
                        if key in resource_positions:
                            dep_type_position = resource_positions[key]
                            if dep_type_position < max_dep_position:
                                order_issues.append(
                                    f"{dependent_type}/{dep_type_id} at position {dep_type_position} "
                                    f"comes before {dependency_type} resources at position {max_dep_position}"
                                )

        if order_issues:
            for issue in order_issues[:5]:  # Show first 5
                result.add_issue(issue)
            if len(order_issues) > 5:
                result.add_info(f"... and {len(order_issues) - 5} more ordering issues")
            result.add_info(
                "Bundle entries should be sorted by dependency order. "
                "Run convert_to_athena_format.py which includes sorting."
            )
        else:
            result.add_info("Bundle entries are properly ordered by dependencies")
            result.validated_count = len(entries)
            result.resource_count = len(entries)
            result.passed = True

        return result

    def validate_athena_metadata(self) -> ValidationResult:
        """
        Validate AthenaHealth-specific metadata and extensions

        Checks for:
        - ah-practice extension
        - ah-chart-sharing-group extension
        - athenaId extension
        - Proper identifier system
        """
        result = ValidationResult(
            "AthenaHealth metadata",
            "ThetaRho Custom Extensions"
        )

        # Resource types that should have athena metadata
        athena_resource_types = [
            'Patient', 'Encounter', 'Observation', 'Condition',
            'MedicationRequest', 'DiagnosticReport', 'Procedure',
            'AllergyIntolerance', 'Immunization', 'Medication'
        ]

        total_resources = 0
        resources_with_metadata = 0

        for res_type in athena_resource_types:
            resources = self.resources_by_type.get(res_type, [])
            for resource in resources:
                total_resources += 1
                res_id = resource.get('id', 'unknown')

                extensions = resource.get('extension', [])
                ext_urls = [ext.get('url', '') for ext in extensions]

                has_practice = any('ah-practice' in url for url in ext_urls)
                has_chart_sharing = any('ah-chart-sharing-group' in url for url in ext_urls)
                has_athena_id = any('athenaId' in url for url in ext_urls)

                identifiers = resource.get('identifier', [])
                has_athena_identifier = any(
                    'athena' in ident.get('system', '').lower()
                    for ident in identifiers
                )

                if has_practice and has_chart_sharing and (has_athena_id or has_athena_identifier):
                    resources_with_metadata += 1

        result.resource_count = total_resources
        result.validated_count = resources_with_metadata

        if total_resources == 0:
            result.add_info("No resources requiring athena metadata found")
            result.passed = True
        elif resources_with_metadata == total_resources:
            result.add_info(
                f"All {total_resources} resources have proper athena metadata (extensions and identifiers)"
            )
            result.passed = True
        elif resources_with_metadata > total_resources * 0.5:  # 50% threshold (lenient for mock patients)
            result.add_warning(
                f"Only {resources_with_metadata}/{total_resources} resources have complete athena metadata. "
                "This is acceptable for mock patients, but production data should have 100% coverage."
            )
            result.passed = True  # Warning only - not critical for HAPI upload
        else:
            result.add_warning(
                f"Only {resources_with_metadata}/{total_resources} resources have athena metadata. "
                "Consider running convert_to_athena_format.py to add missing extensions."
            )
            result.passed = True  # Warning only - athena metadata is not required for HAPI upload

        return result

    def validate_resource_ids(self) -> ValidationResult:
        """
        Validate resource ID format

        Checks for:
        - No UUID format IDs (except Medication resources which may have UUIDs)
        - Numeric IDs with practice prefix (e.g., t1234567)
        - No duplicate IDs
        """
        result = ValidationResult(
            "Resource ID format",
            "ThetaRho ID Convention"
        )

        seen_ids = set()
        uuid_pattern_count = 0
        numeric_id_count = 0
        duplicate_ids = []
        uuid_resources = []

        for entry in self.bundle.get('entry', []):
            resource = entry.get('resource', {})
            res_type = resource.get('resourceType', 'Unknown')
            res_id = resource.get('id')

            if not res_id:
                result.add_warning(f"{res_type} resource missing ID")
                continue

            # Check for duplicates
            if res_id in seen_ids:
                duplicate_ids.append(f"{res_type}/{res_id}")
            seen_ids.add(res_id)

            # Check ID format
            if len(res_id) == 36 and res_id.count('-') == 4:  # UUID format
                uuid_pattern_count += 1
                # UUIDs are acceptable for Medication resources from Synthea
                if res_type != 'Medication':
                    uuid_resources.append(f"{res_type}/{res_id}")
            elif res_id.startswith('t') or res_id.startswith('a-'):
                numeric_id_count += 1

        result.resource_count = len(seen_ids)
        result.validated_count = numeric_id_count

        if duplicate_ids:
            result.add_issue(f"Found {len(duplicate_ids)} duplicate resource IDs: {', '.join(duplicate_ids[:5])}")

        if uuid_resources:
            result.add_warning(
                f"Found {len(uuid_resources)} non-Medication resources with UUID IDs. "
                f"These should be converted to numeric IDs. Examples: {', '.join(uuid_resources[:3])}"
            )

        result.add_info(f"Numeric IDs: {numeric_id_count}, UUID IDs: {uuid_pattern_count}")

        if not duplicate_ids and len(uuid_resources) <= 5:  # Allow a few UUID IDs
            result.passed = True
        elif not duplicate_ids:
            result.passed = True  # Warning only for UUIDs

        return result

    def validate_uuid_identifiers(self) -> ValidationResult:
        """
        Validate that identifiers do not contain UUIDs

        CRITICAL: TRAIS search.py:202 get_ident_from_id() returns identifier[0]['value']
        If first identifier is a Synthea UUID, TRAIS indexes resources to wrong OpenSearch index
        causing image queries and all resource queries to return 0 results.

        Root cause: Resources indexed to UUID-based index (e.g., ac19f5e1-68a7-6c0f-5bc2-6d7f06378437)
        but queries search patient identifier index (e.g., a-11783.e-t8080).
        """
        import re

        result = ValidationResult(
            "UUID identifier removal",
            "TRAIS search.py get_ident_from_id()",
            "Line 202"
        )

        uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

        uuid_systems_to_remove = [
            'https://github.com/synthetichealth/synthea',
            'http://hospital.smarthealthit.org'
        ]

        resources_with_uuid_identifiers = []
        total_checked = 0

        for entry in self.bundle.get('entry', []):
            resource = entry.get('resource', {})
            res_type = resource.get('resourceType')
            res_id = resource.get('id', 'unknown')

            identifiers = resource.get('identifier', [])
            if not identifiers:
                continue

            total_checked += 1

            for idx, identifier in enumerate(identifiers):
                system = identifier.get('system', '')
                value = identifier.get('value', '')

                # Check for Synthea/SmartHealthIT systems
                if any(bad_sys in system for bad_sys in uuid_systems_to_remove):
                    resources_with_uuid_identifiers.append(
                        f"{res_type}/{res_id}: identifier[{idx}] has system '{system}' (should be removed)"
                    )
                    break

                # Check for UUID values
                if uuid_pattern.match(value):
                    resources_with_uuid_identifiers.append(
                        f"{res_type}/{res_id}: identifier[{idx}] has UUID value '{value}' (should be removed)"
                    )
                    break

        result.resource_count = total_checked
        result.validated_count = total_checked - len(resources_with_uuid_identifiers)

        if resources_with_uuid_identifiers:
            result.add_issue(
                f"Found {len(resources_with_uuid_identifiers)} resources with UUID identifiers. "
                "These cause TRAIS to index resources to wrong OpenSearch index, "
                "resulting in 0 results for all queries (images, procedures, conditions, etc.)"
            )
            for issue in resources_with_uuid_identifiers[:10]:
                result.add_issue(f"  - {issue}")
            if len(resources_with_uuid_identifiers) > 10:
                result.add_info(f"  ... and {len(resources_with_uuid_identifiers) - 10} more UUID identifiers")
        else:
            result.add_info(f"No UUID identifiers found in {total_checked} resources")
            result.passed = True

        return result

    def validate_identifier_order(self) -> ValidationResult:
        """
        Validate identifier array ordering

        CRITICAL: TRAIS search.py:202-206 get_ident_from_id() was fixed to look for
        ThetaRho Athena identifier, but proper ordering is still best practice:
        1. Athena ID (a-11783.E-t8080) - MUST be first for backward compatibility
        2. Patient ID (t8080) - For Patient resources only
        3. Other identifiers (SSN, DL, Passport, etc.)
        """
        result = ValidationResult(
            "Identifier ordering (Athena first)",
            "TRAIS search.py get_ident_from_id() + Best Practice",
            "Lines 202-216"
        )

        resources_with_wrong_order = []
        total_checked = 0

        for entry in self.bundle.get('entry', []):
            resource = entry.get('resource', {})
            res_type = resource.get('resourceType')
            res_id = resource.get('id', 'unknown')

            identifiers = resource.get('identifier', [])
            if not identifiers:
                continue

            total_checked += 1

            # Check that first identifier is Athena identifier
            first_identifier = identifiers[0]
            first_system = first_identifier.get('system', '')

            if 'thetarho.com/fhir/identifiers/athena' not in first_system:
                resources_with_wrong_order.append(
                    f"{res_type}/{res_id}: First identifier has system '{first_system}', "
                    f"expected 'https://www.thetarho.com/fhir/identifiers/athena'"
                )

            # For Patient resources, check second identifier is patient ID
            if res_type == 'Patient' and len(identifiers) >= 2:
                second_identifier = identifiers[1]
                second_system = second_identifier.get('system', '')

                if 'thetarho.com/fhir/identifiers/patient' not in second_system:
                    resources_with_wrong_order.append(
                        f"{res_type}/{res_id}: Second identifier has system '{second_system}', "
                        f"expected 'https://www.thetarho.com/fhir/identifiers/patient'"
                    )

        result.resource_count = total_checked
        result.validated_count = total_checked - len(resources_with_wrong_order)

        if resources_with_wrong_order:
            result.add_warning(
                f"Found {len(resources_with_wrong_order)} resources with incorrect identifier ordering. "
                "While TRAIS now searches for Athena identifier, proper ordering is best practice."
            )
            for issue in resources_with_wrong_order[:5]:
                result.add_warning(f"  - {issue}")
            if len(resources_with_wrong_order) > 5:
                result.add_info(f"  ... and {len(resources_with_wrong_order) - 5} more ordering issues")
            result.passed = True  # Warning only, not critical since TRAIS was fixed
        else:
            result.add_info(f"All {total_checked} resources have correct identifier ordering (Athena first)")
            result.passed = True

        return result

    def validate_patient_general_practitioner(self) -> ValidationResult:
        """
        Validate Patient.generalPractitioner exists and references a Practitioner

        CRITICAL: HTMLService.java:674-785 extracts practitioner ID from
        Patient.generalPractitioner for mock patients. Without this, practitionerId
        will be "not_available" causing issues in chat UI initialization.
        """
        result = ValidationResult(
            "Patient.generalPractitioner reference",
            "HTMLService.java",
            "Lines 674-785"
        )

        patients = self.resources_by_type.get('Patient', [])
        result.resource_count = len(patients)

        if result.resource_count == 0:
            result.add_issue("No Patient resource found in bundle")
            return result

        if result.resource_count > 1:
            result.add_warning(f"Found {result.resource_count} Patient resources, expected 1")

        for patient in patients:
            patient_id = patient.get('id', 'unknown')

            if 'generalPractitioner' not in patient:
                result.add_issue(
                    f"Patient/{patient_id}: Missing generalPractitioner field. "
                    "HTMLService will not be able to extract practitioner ID for mock patients."
                )
                continue

            gen_pract = patient['generalPractitioner']

            if not isinstance(gen_pract, list) or len(gen_pract) == 0:
                result.add_issue(
                    f"Patient/{patient_id}: generalPractitioner is not a non-empty array"
                )
                continue

            ref = gen_pract[0].get('reference')
            if not ref or not ref.startswith('Practitioner/'):
                result.add_issue(
                    f"Patient/{patient_id}: generalPractitioner[0].reference invalid or missing. "
                    f"Expected 'Practitioner/xxx', got '{ref}'"
                )
            else:
                result.validated_count += 1
                if self.verbose:
                    result.add_info(f"Patient/{patient_id}: generalPractitioner = {ref}")

        if result.validated_count == result.resource_count:
            result.passed = True

        return result

    def validate_composition_for_encounters(self) -> ValidationResult:
        """
        Validate Composition resources exist for each Encounter

        CRITICAL: FhirQueryService.java:2361-2383 searches for Compositions for each encounter.
        If no Composition found, the ENTIRE encounter is SKIPPED and NO resources are discovered
        (Observations, Conditions, DiagnosticReports, Procedures).

        Each Composition MUST have:
        - section[0].title containing "ssessment" (case-insensitive)
        - encounter reference matching an Encounter ID
        - LOINC codes for type and section
        """
        result = ValidationResult(
            "Composition resources for Encounters",
            "FhirQueryService.java",
            "Lines 2361-2383"
        )

        encounters = self.resources_by_type.get('Encounter', [])
        compositions = self.resources_by_type.get('Composition', [])

        result.resource_count = len(encounters)

        if result.resource_count == 0:
            result.add_info("No Encounter resources in bundle")
            result.passed = True
            return result

        if len(compositions) == 0:
            result.add_issue(
                "No Composition resources found in bundle. "
                "ALL encounters will be skipped by SinceLastVisit query, causing empty externalVisit and chat UI errors."
            )
            return result

        # Build map of encounter IDs to compositions
        encounter_ids = {enc.get('id') for enc in encounters if enc.get('id')}
        encounter_to_composition = {}

        for comp in compositions:
            comp_id = comp.get('id', 'unknown')
            enc_ref = comp.get('encounter', {}).get('reference', '')

            if not enc_ref:
                result.add_warning(f"Composition/{comp_id}: No encounter reference")
                continue

            enc_id = enc_ref.split('/')[-1]
            encounter_to_composition[enc_id] = comp

            # Validate section title contains "ssessment"
            sections = comp.get('section', [])
            if not sections:
                result.add_issue(
                    f"Composition/{comp_id}: No sections found. "
                    "FhirQueryService requires section with title containing 'ssessment'."
                )
                continue

            has_assessment_section = False
            for section in sections:
                title = section.get('title', '')
                if 'ssessment' in title.lower():
                    has_assessment_section = True
                    break

            if not has_assessment_section:
                result.add_issue(
                    f"Composition/{comp_id}: No section with title containing 'ssessment'. "
                    f"Section titles: {[s.get('title') for s in sections]}. "
                    "This encounter will be SKIPPED by SinceLastVisit query."
                )

            # Validate LOINC codes
            type_code = comp.get('type', {}).get('coding', [{}])[0].get('code')
            if type_code != '34133-9':
                result.add_warning(
                    f"Composition/{comp_id}: type.coding[0].code should be '34133-9' (Summary of episode note), "
                    f"got '{type_code}'"
                )

            if sections and has_assessment_section:
                section_code = sections[0].get('code', {}).get('coding', [{}])[0].get('code')
                if section_code != '51847-2':
                    result.add_warning(
                        f"Composition/{comp_id}: section[0].code.coding[0].code should be '51847-2' (Assessment and Plan), "
                        f"got '{section_code}'"
                    )

        # Check which encounters have Compositions
        encounters_with_compositions = []
        encounters_without_compositions = []

        for enc_id in encounter_ids:
            if enc_id in encounter_to_composition:
                encounters_with_compositions.append(enc_id)
                result.validated_count += 1
            else:
                encounters_without_compositions.append(enc_id)

        if encounters_without_compositions:
            result.add_issue(
                f"{len(encounters_without_compositions)} encounter(s) have NO Composition: "
                f"{', '.join(encounters_without_compositions[:5])}. "
                "These encounters will be SKIPPED by SinceLastVisit, "
                "causing incomplete data and potential chat UI errors."
            )

        if result.validated_count == result.resource_count:
            result.passed = True
            result.add_info(
                f"All {result.resource_count} encounters have Composition resources with valid Assessment sections"
            )
        elif result.validated_count > 0:
            result.add_info(
                f"{result.validated_count}/{result.resource_count} encounters have Compositions"
            )

        return result

    def validate_chat_ui_data_structure(self) -> ValidationResult:
        """
        Validate that bundle will produce complete data structure for chat UI

        Ensures all required fields for window.datadoc will be populated:
        - patient (demographics from Patient resource)
        - practitionerId (from Patient.generalPractitioner)
        - sinceLastVisit_V2.summary.externalVisit (from Compositions + Encounters)
        - sinceLastVisit_V2.summary.labs (from Observations)
        """
        result = ValidationResult(
            "Chat UI data structure requirements",
            "HTMLService.prepareJsonData + Chat UI"
        )

        # Check 1: Patient demographics
        patients = self.resources_by_type.get('Patient', [])
        if not patients:
            result.add_issue("No Patient resource - chat UI cannot render patient demographics")
        else:
            patient = patients[0]
            has_name = bool(patient.get('name'))
            has_gender = bool(patient.get('gender'))
            has_dob = bool(patient.get('birthDate'))

            if not (has_name and has_gender and has_dob):
                missing = []
                if not has_name: missing.append('name')
                if not has_gender: missing.append('gender')
                if not has_dob: missing.append('birthDate')
                result.add_warning(
                    f"Patient/{patient.get('id')}: Missing demographics: {', '.join(missing)}"
                )

        # Check 2: Practitioner reference
        has_practitioner_ref = False
        if patients and patients[0].get('generalPractitioner'):
            has_practitioner_ref = True
        if not has_practitioner_ref:
            result.add_issue(
                "Patient.generalPractitioner missing - practitionerId will be 'not_available', "
                "may cause chat UI initialization errors"
            )

        # Check 3: Compositions for encounters
        encounters = self.resources_by_type.get('Encounter', [])
        compositions = self.resources_by_type.get('Composition', [])

        if encounters and not compositions:
            result.add_issue(
                f"Found {len(encounters)} Encounters but NO Compositions - "
                "sinceLastVisit_V2.summary.externalVisit will be EMPTY {}, "
                "causing 'Cannot convert undefined or null to object' error in chat UI"
            )
        elif encounters and len(compositions) < len(encounters):
            result.add_warning(
                f"Only {len(compositions)}/{len(encounters)} encounters have Compositions - "
                "some encounters will be missing from externalVisit"
            )

        # Check 4: Clinical resources linked to encounters
        has_conditions = len(self.resources_by_type.get('Condition', [])) > 0
        has_observations = len(self.resources_by_type.get('Observation', [])) > 0
        has_meds = len(self.resources_by_type.get('MedicationRequest', [])) > 0
        has_reports = len(self.resources_by_type.get('DiagnosticReport', [])) > 0

        if not any([has_conditions, has_observations, has_meds, has_reports]):
            result.add_warning(
                "No clinical resources (Conditions, Observations, MedicationRequests, DiagnosticReports) - "
                "encounters will have empty resource arrays"
            )

        # Determine pass/fail
        critical_checks = [
            bool(patients),
            has_practitioner_ref,
            not (encounters and not compositions)  # Fail if encounters exist but no compositions
        ]

        if all(critical_checks):
            result.passed = True
            result.add_info(
                "Bundle structure meets minimum requirements for chat UI rendering"
            )
        else:
            result.add_info(
                "Bundle WILL cause chat UI errors due to missing critical data"
            )

        return result

    def validate_reference_integrity(self) -> ValidationResult:
        """
        Validate that critical Reference fields exist and have proper structure
        (Note: We don't validate that referenced resources exist, just structure)
        """
        result = ValidationResult(
            "Reference field integrity",
            "FHIR R4 Specification"
        )

        critical_references = {
            'MedicationRequest': ['subject', 'requester'],
            'Encounter': ['subject'],
            'Observation': ['subject'],
            'Condition': ['subject'],
            'DiagnosticReport': ['subject'],
            'Procedure': ['subject'],
            'AllergyIntolerance': ['patient'],
            'Immunization': ['patient']
        }

        issues_count = 0
        checked_count = 0

        for resource_type, ref_fields in critical_references.items():
            resources = self.resources_by_type.get(resource_type, [])
            for resource in resources:
                res_id = resource.get('id', 'unknown')
                checked_count += 1

                for field in ref_fields:
                    if field not in resource:
                        result.add_warning(
                            f"{resource_type}/{res_id}: Missing '{field}' reference"
                        )
                        issues_count += 1
                    elif not isinstance(resource[field], dict):
                        result.add_issue(
                            f"{resource_type}/{res_id}: '{field}' is not a valid Reference"
                        )
                        issues_count += 1

        if issues_count == 0:
            result.add_info(f"Checked {checked_count} resources for critical references")
            result.passed = True
        else:
            result.add_info(f"Found issues in {issues_count} references across {checked_count} resources")

        return result

    def validate_dangling_encounter_references(self) -> ValidationResult:
        """
        Validate that all Encounter references point to existing Encounters

        CRITICAL: HAPI FHIR upload fails with "Resource Encounter/xxx not found" if
        resources reference encounters that don't exist in the bundle.

        Common cause: convert_to_athena_format.py removes empty wellness encounters
        but Claims/EOBs may still reference them.
        """
        result = ValidationResult(
            "Dangling Encounter references",
            "HAPI FHIR Bundle Upload"
        )

        # Build set of all Encounter IDs in bundle
        encounter_ids = set()
        encounters = self.resources_by_type.get('Encounter', [])
        for enc in encounters:
            enc_id = enc.get('id')
            if enc_id:
                encounter_ids.add(enc_id)

        result.add_info(f"Found {len(encounter_ids)} Encounter resources in bundle")

        # Resource types that can reference Encounters
        encounter_reference_types = {
            'Observation': lambda r: [r.get('encounter', {}).get('reference', '').replace('Encounter/', '')],
            'DiagnosticReport': lambda r: [r.get('encounter', {}).get('reference', '').replace('Encounter/', '')],
            'MedicationRequest': lambda r: [r.get('encounter', {}).get('reference', '').replace('Encounter/', '')],
            'Condition': lambda r: [r.get('encounter', {}).get('reference', '').replace('Encounter/', '')],
            'Procedure': lambda r: [r.get('encounter', {}).get('reference', '').replace('Encounter/', '')],
            'Immunization': lambda r: [r.get('encounter', {}).get('reference', '').replace('Encounter/', '')],
            'Composition': lambda r: [r.get('encounter', {}).get('reference', '').replace('Encounter/', '')],
            'DocumentReference': lambda r: [e.get('reference', '').replace('Encounter/', '') for e in r.get('context', {}).get('encounter', [])],
            'MedicationAdministration': lambda r: [r.get('context', {}).get('reference', '').replace('Encounter/', '')],
            'CarePlan': lambda r: [r.get('encounter', {}).get('reference', '').replace('Encounter/', '')] if isinstance(r.get('encounter'), dict) else [],
            'Claim': lambda r: [e.get('reference', '').replace('Encounter/', '') for item in r.get('item', []) for e in item.get('encounter', [])],
            'ExplanationOfBenefit': lambda r: [e.get('reference', '').replace('Encounter/', '') for item in r.get('item', []) for e in item.get('encounter', [])]
        }

        dangling_references = []
        checked_resources = 0

        for res_type, extract_func in encounter_reference_types.items():
            resources = self.resources_by_type.get(res_type, [])
            for resource in resources:
                res_id = resource.get('id', 'unknown')
                checked_resources += 1

                enc_refs = extract_func(resource)
                for enc_ref in enc_refs:
                    if enc_ref and enc_ref not in encounter_ids:
                        dangling_references.append(
                            f"{res_type}/{res_id} references Encounter/{enc_ref} which doesn't exist"
                        )

        result.resource_count = checked_resources
        result.validated_count = checked_resources - len(dangling_references)

        if dangling_references:
            result.add_issue(
                f"Found {len(dangling_references)} dangling Encounter references. "
                "HAPI upload will fail! Run convert_to_athena_format.py to fix."
            )
            for ref in dangling_references[:10]:
                result.add_issue(f"  - {ref}")
            if len(dangling_references) > 10:
                result.add_info(f"  ... and {len(dangling_references) - 10} more dangling references")
        else:
            result.add_info(f"All {checked_resources} resources have valid Encounter references")
            result.passed = True

        return result

    def validate_empty_encounters(self) -> ValidationResult:
        """
        Validate that Encounters have linked clinical resources

        WARNING: Encounters with no linked resources provide no clinical value
        and may cause issues in SinceLastVisit queries.
        """
        result = ValidationResult(
            "Empty Encounters (no linked resources)",
            "Clinical Data Quality"
        )

        encounters = self.resources_by_type.get('Encounter', [])
        result.resource_count = len(encounters)

        if result.resource_count == 0:
            result.add_info("No Encounter resources in bundle")
            result.passed = True
            return result

        # Build map of encounter IDs to linked resources
        encounter_resources = {enc['id']: {
            'type': enc.get('type', [{}])[0].get('text', 'Unknown'),
            'date': enc.get('period', {}).get('start', ''),
            'resources': []
        } for enc in encounters if enc.get('id')}

        # Resource types that link to Encounters
        linkable_types = ['Observation', 'DiagnosticReport', 'MedicationRequest',
                         'Condition', 'Procedure', 'Immunization']

        for res_type in linkable_types:
            resources = self.resources_by_type.get(res_type, [])
            for resource in resources:
                enc_ref = resource.get('encounter', {}).get('reference', '').replace('Encounter/', '')
                if enc_ref and enc_ref in encounter_resources:
                    encounter_resources[enc_ref]['resources'].append(res_type)

        # Check for empty encounters
        empty_encounters = []
        wellness_encounters = []

        for enc_id, enc_data in encounter_resources.items():
            if not enc_data['resources']:
                enc_type = enc_data['type']
                if 'Well child' in enc_type or 'General examination' in enc_type:
                    wellness_encounters.append(f"{enc_id} ({enc_type})")
                else:
                    empty_encounters.append(f"{enc_id} ({enc_type})")

        result.validated_count = result.resource_count - len(empty_encounters) - len(wellness_encounters)

        if wellness_encounters:
            result.add_warning(
                f"Found {len(wellness_encounters)} wellness encounters with no linked resources. "
                "These should be removed by convert_to_athena_format.py"
            )
            for enc in wellness_encounters[:5]:
                result.add_warning(f"  - Encounter/{enc}")

        if empty_encounters:
            result.add_warning(
                f"Found {len(empty_encounters)} non-wellness encounters with no linked resources. "
                "These provide no clinical value."
            )
            for enc in empty_encounters[:5]:
                result.add_warning(f"  - Encounter/{enc}")

        if not empty_encounters and not wellness_encounters:
            result.add_info(f"All {result.resource_count} encounters have linked clinical resources")
            result.passed = True
        else:
            result.passed = True  # Warnings only

        return result

    def run_all_validations(self) -> bool:
        """Run all validation checks"""
        print("=" * 80)
        print("THETARHO PATIENT BUNDLE VALIDATOR")
        print("=" * 80)
        print(f"\nBundle: {self.bundle_path}")
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        # Load bundle
        if not self.load_bundle():
            return False

        print(f"Loaded bundle with {len(self.bundle.get('entry', []))} resources")
        print()

        # Run validations in order of criticality
        validations = [
            # Critical structural validations
            self.validate_bundle_structure,
            self.validate_resource_inventory,
            self.validate_resource_ids,

            # CRITICAL: UUID identifier validations (NEW - prevents TRAIS indexing failures)
            self.validate_uuid_identifiers,
            self.validate_identifier_order,

            # Critical HAPI upload validations
            self.validate_medication_resources,
            self.validate_bundle_dependency_order,

            # Critical field validations (prevent ClassCastException/NullPointerException)
            self.validate_medication_request,
            self.validate_encounter_service_provider,
            self.validate_allergy_intolerance,
            self.validate_condition,

            # Important field validations
            self.validate_immunization,
            self.validate_observation,
            self.validate_diagnostic_report,
            self.validate_procedure,
            self.validate_medication_administration,

            # ThetaRho-specific validations
            self.validate_athena_metadata,
            self.validate_patient_tagging_requirements,
            self.validate_reference_integrity,

            # CRITICAL: Encounter reference integrity (NEW - prevents HAPI upload errors)
            self.validate_dangling_encounter_references,
            self.validate_empty_encounters,

            # CRITICAL: Chat UI and SinceLastVisit requirements
            self.validate_patient_general_practitioner,
            self.validate_composition_for_encounters,
            self.validate_chat_ui_data_structure,
        ]

        print("Running validations...")
        print("-" * 80)

        for validation_func in validations:
            result = validation_func()
            self.results.append(result)

            # Print immediate result
            print(f"\n{result}")

            # Show details if verbose or if failed
            if not result.passed or self.verbose:
                for issue in result.issues:
                    print(f"  ❌ {issue}")

                if self.verbose:
                    for warning in result.warnings:
                        print(f"  ⚠️  {warning}")

                    for info in result.info:  # Show all info in verbose mode
                        print(f"  ℹ️  {info}")
                elif not result.passed:
                    # In non-verbose mode, show limited info for failed checks
                    for info in result.info[:3]:
                        print(f"  ℹ️  {info}")
                    if len(result.info) > 3:
                        print(f"  ℹ️  ... and {len(result.info) - 3} more info messages")

        print()
        return True

    def print_summary(self):
        """Print validation summary"""
        print("=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        print()

        passed_count = sum(1 for r in self.results if r.passed)
        failed_count = len(self.results) - passed_count

        total_issues = sum(len(r.issues) for r in self.results)
        total_warnings = sum(len(r.warnings) for r in self.results)

        print(f"Total Checks: {len(self.results)}")
        print(f"✅ Passed: {passed_count}")
        print(f"❌ Failed: {failed_count}")
        print()
        print(f"Critical Issues: {total_issues}")
        print(f"Warnings: {total_warnings}")
        print()

        if failed_count == 0:
            print("🎉 " + "=" * 74 + " 🎉")
            print("   ALL VALIDATIONS PASSED - BUNDLE READY FOR PRODUCTION")
            print("🎉 " + "=" * 74 + " 🎉")
            print()
            print("This bundle meets all requirements for:")
            print("  ✅ FhirDataValidationQueryService (ThetaRhoAppServer)")
            print("  ✅ FhirQueryService (ThetaRhoAppServer)")
            print("  ✅ PatientTaggingService (TRDataServices)")
            print("  ✅ TRAIS AI Service")
            print()
            print("Next steps:")
            print("  1. Upload to HAPI FHIR: ./scripts/upload_fhir_bundles_to_hapi.sh <patient_id>")
            print("  2. Test HTML generation workflow")
            print("  3. Verify TRAIS AI indexing and QA")
        else:
            print("❌ VALIDATION FAILED")
            print()
            print(f"Found {total_issues} critical issue(s) that must be fixed:")
            print()

            for result in self.results:
                if not result.passed:
                    print(f"  ❌ {result.check_name} ({result.service})")
                    for issue in result.issues[:3]:
                        print(f"     - {issue}")
                    if len(result.issues) > 3:
                        print(f"     - ... and {len(result.issues) - 3} more issues")

            print()
            print("Recommended fixes:")
            print("  1. Re-run conversion script: python3 scripts/convert_to_athena_format.py")
            print("  2. Ensure all fix functions are enabled (convert_medication_codeable_concept_to_reference, etc.)")
            print("  3. Validate again after fixes")

        print()

    def generate_markdown_report(self, output_path: str):
        """Generate detailed markdown validation report"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# Patient Bundle Validation Report\n\n")
            f.write(f"**Bundle**: {os.path.basename(self.bundle_path)}\n")
            f.write(f"**Validation Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Total Resources**: {len(self.bundle.get('entry', []))}\n\n")

            passed_count = sum(1 for r in self.results if r.passed)
            failed_count = len(self.results) - passed_count
            total_issues = sum(len(r.issues) for r in self.results)
            total_warnings = sum(len(r.warnings) for r in self.results)

            f.write(f"## Summary\n\n")
            f.write(f"- Total Checks: {len(self.results)}\n")
            f.write(f"- ✅ Passed: {passed_count}\n")
            f.write(f"- ❌ Failed: {failed_count}\n")
            f.write(f"- Critical Issues: {total_issues}\n")
            f.write(f"- Warnings: {total_warnings}\n\n")

            if failed_count == 0:
                f.write(f"**Status**: ✅ READY FOR PRODUCTION\n\n")
            else:
                f.write(f"**Status**: ❌ NEEDS FIXES\n\n")

            f.write(f"---\n\n")
            f.write(f"## Detailed Results\n\n")

            for result in self.results:
                status_icon = "✅" if result.passed else "❌"
                f.write(f"### {status_icon} {result.check_name}\n\n")
                f.write(f"**Service**: {result.service}\n")
                if result.line_ref:
                    f.write(f"**Code Reference**: {result.line_ref}\n")
                if result.resource_count > 0:
                    f.write(f"**Resources**: {result.validated_count}/{result.resource_count} validated\n")
                f.write(f"\n")

                if result.issues:
                    f.write(f"**Critical Issues**:\n")
                    for issue in result.issues:
                        f.write(f"- ❌ {issue}\n")
                    f.write(f"\n")

                if result.warnings:
                    f.write(f"**Warnings**:\n")
                    for warning in result.warnings:
                        f.write(f"- ⚠️ {warning}\n")
                    f.write(f"\n")

                if result.info and self.verbose:
                    f.write(f"**Details**:\n")
                    for info in result.info:
                        f.write(f"- ℹ️ {info}\n")
                    f.write(f"\n")

                f.write(f"---\n\n")

            # Resource inventory table
            f.write(f"## Resource Inventory\n\n")
            f.write(f"| Resource Type | Count |\n")
            f.write(f"|--------------|-------|\n")

            for resource_type in sorted(self.resources_by_type.keys()):
                count = len(self.resources_by_type[resource_type])
                f.write(f"| {resource_type} | {count} |\n")

            f.write(f"\n**Total**: {len(self.bundle.get('entry', []))} resources\n")

        print(f"📄 Detailed report saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate FHIR patient bundles against ThetaRho service requirements",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 validate_patient.py --input patient_bundle.json
  python3 validate_patient.py --input t8_bundle.json --verbose
  python3 validate_patient.py --input t1_bundle.json --output validation_report.md
  python3 validate_patient.py --input t8_bundle.json --verbose --output t8_report.md

Exit codes:
  0 - All validations passed
  1 - Critical issues found
  2 - File/parsing errors
        """
    )

    parser.add_argument(
        '--input',
        required=True,
        help='Path to FHIR bundle JSON file'
    )

    parser.add_argument(
        '--output',
        help='Path to save detailed markdown report (optional)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed validation information'
    )

    args = parser.parse_args()

    # Create validator
    validator = PatientBundleValidator(args.input, verbose=args.verbose)

    # Run validations
    success = validator.run_all_validations()

    if not success:
        return 2

    # Print summary
    validator.print_summary()

    # Generate markdown report if requested
    if args.output:
        validator.generate_markdown_report(args.output)

    # Return exit code based on results
    failed_count = sum(1 for r in validator.results if not r.passed)
    return 0 if failed_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())

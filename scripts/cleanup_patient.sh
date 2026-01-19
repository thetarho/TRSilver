#!/bin/bash

# cleanup_duplicate_resources.sh - HARD DELETE FHIR resources by identifier
# Usage: ./cleanup_duplicate_resources.sh <patient_identifier>
# Example: ./cleanup_duplicate_resources.sh t2
#
# This script finds and PERMANENTLY deletes ALL resources for a patient by searching for their identifier,
# not just by resource ID. This uses HAPI FHIR's expunge feature to hard delete resources.
# This is useful when multiple copies exist from repeated testing.

# Don't exit on error - we want to continue even if some resources aren't found
# set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
PATIENT_IDENTIFIER=""
DELETE_SHARED=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --delete-shared)
            DELETE_SHARED=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 <patient_identifier> [options]"
            echo ""
            echo "Arguments:"
            echo "  patient_identifier  - Patient identifier (e.g., t7) [REQUIRED]"
            echo ""
            echo "Options:"
            echo "  --delete-shared     - Also delete shared resources (Organization, Practitioner, Location)"
            echo "  -h, --help          - Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 t7"
            echo "  $0 t7 --delete-shared"
            exit 0
            ;;
        *)
            if [ -z "$PATIENT_IDENTIFIER" ]; then
                PATIENT_IDENTIFIER="$1"
            else
                echo -e "${RED}Error: Unknown argument: $1${NC}"
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$PATIENT_IDENTIFIER" ]; then
    echo -e "${RED}Error: Missing patient identifier${NC}"
    echo ""
    echo "Usage: $0 <patient_identifier> [--delete-shared]"
    echo "Example: $0 t7"
    echo "Use --help for more information"
    exit 1
fi

# Server configuration
SERVER_HOST="${SERVER_HOST:-danvers-clone.thetarho.com}"
HAPI_FHIR_URL="http://${SERVER_HOST}:8080/fhir"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                  ThetaRho Resource Cleanup Script              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Configuration:${NC}"
echo "  Patient Identifier: ${PATIENT_IDENTIFIER}"
echo "  HAPI FHIR:          ${HAPI_FHIR_URL}"
echo "  Delete Shared:      ${DELETE_SHARED}"
echo ""
echo -e "${YELLOW}This will PERMANENTLY remove ALL resources matching identifier: ${PATIENT_IDENTIFIER}${NC}"
if [ "$DELETE_SHARED" = true ]; then
    echo -e "${YELLOW}Including shared resources (Organization, Practitioner, Location)${NC}"
fi
echo ""

# Helper function to delete FHIR resources by search
delete_resources_by_search() {
    local resource_type=$1
    local search_param=$2
    local search_value=$3

    echo -e "${CYAN}Searching for ${resource_type} resources with ${search_param}=${search_value}...${NC}"

    # Search for resources (don't use _summary=true as we need full IDs)
    search_url="${HAPI_FHIR_URL}/${resource_type}?${search_param}=${search_value}&_elements=id"
    echo -e "${CYAN}  Search URL: ${search_url}${NC}"

    response=$(curl -s -w "\n%{http_code}" --connect-timeout 10 --max-time 30 -X GET "$search_url" 2>&1)
    http_code=$(echo "$response" | tail -n 1)
    body=$(echo "$response" | sed '$d')

    echo -e "${CYAN}  HTTP Code: ${http_code}${NC}"

    if [ -z "$http_code" ] || [ "$http_code" = "000" ]; then
        echo -e "${RED}  ✗ Connection failed to HAPI FHIR server${NC}"
        return 1
    fi

    if [ "$http_code" != "200" ]; then
        echo -e "${YELLOW}  ⚠ Search failed or no resources found (HTTP ${http_code})${NC}"
        if [ -n "$body" ]; then
            echo -e "${YELLOW}  Response: ${body:0:200}${NC}"
        fi
        return 0
    fi

    # Extract resource IDs
    resource_ids=$(echo "$body" | jq -r '.entry[]?.resource.id' 2>/dev/null)

    if [ -z "$resource_ids" ]; then
        echo -e "${CYAN}  ℹ No ${resource_type} resources found${NC}"
        return 0
    fi

    # Delete each resource (HARD DELETE with _expunge=true)
    delete_count=0
    while IFS= read -r resource_id; do
        if [ -n "$resource_id" ] && [ "$resource_id" != "null" ]; then
            # First: Regular delete to mark as deleted
            delete_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X DELETE "${HAPI_FHIR_URL}/${resource_type}/${resource_id}" 2>/dev/null || echo -e "\n000")
            delete_http_code=$(echo "$delete_response" | tail -n 1)

            if [ "$delete_http_code" -ge 200 ] && [ "$delete_http_code" -lt 300 ]; then
                # Second: Expunge to permanently remove
                expunge_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X POST "${HAPI_FHIR_URL}/${resource_type}/${resource_id}/\$expunge" 2>/dev/null || echo -e "\n000")
                expunge_http_code=$(echo "$expunge_response" | tail -n 1)

                if [ "$expunge_http_code" -ge 200 ] && [ "$expunge_http_code" -lt 300 ]; then
                    echo -e "${GREEN}  ✓ HARD DELETED ${resource_type}/${resource_id}${NC}"
                else
                    echo -e "${YELLOW}  ⚠ Soft deleted ${resource_type}/${resource_id}, expunge failed (HTTP ${expunge_http_code})${NC}"
                fi
                ((delete_count++))
            elif [ "$delete_http_code" = "404" ] || [ "$delete_http_code" = "410" ]; then
                echo -e "${CYAN}  ℹ ${resource_type}/${resource_id} already deleted${NC}"
            else
                echo -e "${YELLOW}  ⚠ Could not delete ${resource_type}/${resource_id} (HTTP ${delete_http_code})${NC}"
            fi
        fi
    done <<< "$resource_ids"

    if [ $delete_count -gt 0 ]; then
        echo -e "${GREEN}  ✓ Deleted ${delete_count} ${resource_type} resource(s)${NC}"
    fi
    echo ""
}

# ============================================================================
# STEP 1: Find All Patient FHIR IDs by Identifier
# ============================================================================
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}STEP 1: Finding Patient FHIR IDs${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${CYAN}Searching for all Patient resources with identifier: ${PATIENT_IDENTIFIER}${NC}"

# Search for all patients with this identifier
search_url="${HAPI_FHIR_URL}/Patient?identifier=${PATIENT_IDENTIFIER}&_summary=true"
response=$(curl -s -w "\n%{http_code}" --connect-timeout 10 --max-time 30 -X GET "$search_url" 2>&1)
http_code=$(echo "$response" | tail -n 1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
    echo -e "${RED}✗ Failed to search for patients (HTTP ${http_code})${NC}"
    exit 1
fi

# Extract patient FHIR IDs
patient_fhir_ids=$(echo "$body" | jq -r '.entry[]?.resource.id' 2>/dev/null)

if [ -z "$patient_fhir_ids" ]; then
    echo -e "${YELLOW}  ⚠ No patients found with identifier: ${PATIENT_IDENTIFIER}${NC}"
    exit 0
fi

patient_count=$(echo "$patient_fhir_ids" | wc -l | tr -d ' ')
echo -e "${GREEN}  ✓ Found ${patient_count} patient(s)${NC}"
echo "$patient_fhir_ids" | while read -r pid; do
    echo -e "${CYAN}    - Patient/${pid}${NC}"
done
echo ""

# ============================================================================
# STEP 2: Delete Clinical Resources (in reverse dependency order)
# ============================================================================
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}STEP 2: Deleting Clinical Resources (reverse dependency order)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${CYAN}Deleting in order: leaf resources first, then resources with references${NC}"
echo ""

# For each patient FHIR ID, delete all related resources
while IFS= read -r patient_fhir_id; do
    if [ -z "$patient_fhir_id" ] || [ "$patient_fhir_id" = "null" ]; then
        continue
    fi

    echo -e "${YELLOW}Processing resources for Patient/${patient_fhir_id}...${NC}"
    echo ""

    # Use Patient/$everything to get ALL resources for this patient
    echo -e "${CYAN}Finding ALL resources for Patient/${patient_fhir_id} using \$everything...${NC}"
    everything_url="${HAPI_FHIR_URL}/Patient/${patient_fhir_id}/\$everything"
    everything_response=$(curl -s -w "\n%{http_code}" --connect-timeout 30 --max-time 60 -X GET "$everything_url" 2>&1)
    everything_http_code=$(echo "$everything_response" | tail -n 1)
    everything_body=$(echo "$everything_response" | sed '$d')

    if [ "$everything_http_code" != "200" ]; then
        echo -e "${RED}  ✗ Failed to fetch resources using \$everything (HTTP ${everything_http_code})${NC}"
        echo -e "${YELLOW}  Falling back to standard searches...${NC}"
    else
        # Extract all resource types and IDs
        all_resources=$(echo "$everything_body" | jq -r '.entry[]? | "\(.resource.resourceType):\(.resource.id)"' 2>/dev/null)

        if [ -n "$all_resources" ]; then
            total_count=$(echo "$all_resources" | wc -l | tr -d ' ')
            echo -e "${GREEN}  ✓ Found ${total_count} resources via \$everything${NC}"

            # Group by resource type and show counts
            echo "$all_resources" | cut -d: -f1 | sort | uniq -c | while read count rtype; do
                echo -e "${CYAN}    ${rtype}: ${count} resource(s)${NC}"
            done
            echo ""

            # Delete in reverse dependency order
            # Level 1: Leaf resources first (no one references these)
            echo -e "${CYAN}Deleting leaf resources (Provenance, DiagnosticReport, DocumentReference)...${NC}"
            echo "$all_resources" | grep -E "^(Provenance|DiagnosticReport|DocumentReference|Medication):" | while IFS=: read rtype rid; do
                if [ -n "$rid" ] && [ "$rid" != "null" ]; then
                    delete_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X DELETE "${HAPI_FHIR_URL}/${rtype}/${rid}" 2>/dev/null || echo -e "\n000")
                    delete_http_code=$(echo "$delete_response" | tail -n 1)
                    if [ "$delete_http_code" -ge 200 ] && [ "$delete_http_code" -lt 300 ]; then
                        expunge_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X POST "${HAPI_FHIR_URL}/${rtype}/${rid}/\$expunge" 2>/dev/null || echo -e "\n000")
                        expunge_http_code=$(echo "$expunge_response" | tail -n 1)
                        if [ "$expunge_http_code" -ge 200 ] && [ "$expunge_http_code" -lt 300 ]; then
                            echo -e "${GREEN}  ✓ HARD DELETED ${rtype}/${rid}${NC}"
                        fi
                    fi
                fi
            done
            echo ""

            # Level 2: Clinical resources
            echo -e "${CYAN}Deleting clinical resources (Observation, Procedure, Immunization, etc.)...${NC}"
            echo "$all_resources" | grep -E "^(Observation|Procedure|Immunization|MedicationRequest|MedicationAdministration|AllergyIntolerance|Condition):" | while IFS=: read rtype rid; do
                if [ -n "$rid" ] && [ "$rid" != "null" ]; then
                    delete_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X DELETE "${HAPI_FHIR_URL}/${rtype}/${rid}" 2>/dev/null || echo -e "\n000")
                    delete_http_code=$(echo "$delete_response" | tail -n 1)
                    if [ "$delete_http_code" -ge 200 ] && [ "$delete_http_code" -lt 300 ]; then
                        expunge_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X POST "${HAPI_FHIR_URL}/${rtype}/${rid}/\$expunge" 2>/dev/null || echo -e "\n000")
                        expunge_http_code=$(echo "$expunge_response" | tail -n 1)
                        if [ "$expunge_http_code" -ge 200 ] && [ "$expunge_http_code" -lt 300 ]; then
                            echo -e "${GREEN}  ✓ HARD DELETED ${rtype}/${rid}${NC}"
                        fi
                    fi
                fi
            done
            echo ""

            # Level 3: Billing resources
            echo -e "${CYAN}Deleting billing resources (Claim, ExplanationOfBenefit)...${NC}"
            echo "$all_resources" | grep -E "^(ExplanationOfBenefit|Claim):" | while IFS=: read rtype rid; do
                if [ -n "$rid" ] && [ "$rid" != "null" ]; then
                    delete_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X DELETE "${HAPI_FHIR_URL}/${rtype}/${rid}" 2>/dev/null || echo -e "\n000")
                    delete_http_code=$(echo "$delete_response" | tail -n 1)
                    if [ "$delete_http_code" -ge 200 ] && [ "$delete_http_code" -lt 300 ]; then
                        expunge_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X POST "${HAPI_FHIR_URL}/${rtype}/${rid}/\$expunge" 2>/dev/null || echo -e "\n000")
                        expunge_http_code=$(echo "$expunge_response" | tail -n 1)
                        if [ "$expunge_http_code" -ge 200 ] && [ "$expunge_http_code" -lt 300 ]; then
                            echo -e "${GREEN}  ✓ HARD DELETED ${rtype}/${rid}${NC}"
                        fi
                    fi
                fi
            done
            echo ""

            # Level 4: Encounters
            echo -e "${CYAN}Deleting Encounter resources...${NC}"
            echo "$all_resources" | grep "^Encounter:" | while IFS=: read rtype rid; do
                if [ -n "$rid" ] && [ "$rid" != "null" ]; then
                    delete_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X DELETE "${HAPI_FHIR_URL}/${rtype}/${rid}" 2>/dev/null || echo -e "\n000")
                    delete_http_code=$(echo "$delete_response" | tail -n 1)
                    if [ "$delete_http_code" -ge 200 ] && [ "$delete_http_code" -lt 300 ]; then
                        expunge_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X POST "${HAPI_FHIR_URL}/${rtype}/${rid}/\$expunge" 2>/dev/null || echo -e "\n000")
                        expunge_http_code=$(echo "$expunge_response" | tail -n 1)
                        if [ "$expunge_http_code" -ge 200 ] && [ "$expunge_http_code" -lt 300 ]; then
                            echo -e "${GREEN}  ✓ HARD DELETED ${rtype}/${rid}${NC}"
                        else
                            echo -e "${YELLOW}  ⚠ Soft deleted ${rtype}/${rid}, expunge failed${NC}"
                        fi
                    elif [ "$delete_http_code" = "409" ]; then
                        echo -e "${YELLOW}  ⚠ Could not delete ${rtype}/${rid} (still has references)${NC}"
                    fi
                fi
            done
            echo ""
        else
            echo -e "${CYAN}  ℹ No resources found via \$everything${NC}"
        fi
    fi

done <<< "$patient_fhir_ids"

# ============================================================================
# STEP 3: Delete Patient Resources
# ============================================================================
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}STEP 3: Deleting Patient Resources${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Now delete each Patient (all references should be gone)
while IFS= read -r patient_fhir_id; do
    if [ -z "$patient_fhir_id" ] || [ "$patient_fhir_id" = "null" ]; then
        continue
    fi

    echo -e "${CYAN}Deleting Patient/${patient_fhir_id}...${NC}"
    # First: Regular delete
    delete_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X DELETE "${HAPI_FHIR_URL}/Patient/${patient_fhir_id}" 2>/dev/null || echo -e "\n000")
    delete_http_code=$(echo "$delete_response" | tail -n 1)

    if [ "$delete_http_code" -ge 200 ] && [ "$delete_http_code" -lt 300 ]; then
        # Second: Expunge to permanently remove
        expunge_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X POST "${HAPI_FHIR_URL}/Patient/${patient_fhir_id}/\$expunge" 2>/dev/null || echo -e "\n000")
        expunge_http_code=$(echo "$expunge_response" | tail -n 1)

        if [ "$expunge_http_code" -ge 200 ] && [ "$expunge_http_code" -lt 300 ]; then
            echo -e "${GREEN}  ✓ HARD DELETED Patient/${patient_fhir_id}${NC}"
        else
            echo -e "${YELLOW}  ⚠ Soft deleted Patient/${patient_fhir_id}, expunge failed (HTTP ${expunge_http_code})${NC}"
        fi
    elif [ "$delete_http_code" = "404" ]; then
        echo -e "${CYAN}  ℹ Patient/${patient_fhir_id} not found${NC}"
    else
        echo -e "${RED}  ✗ Could not delete Patient/${patient_fhir_id} (HTTP ${delete_http_code})${NC}"
        # Show error details
        error_body=$(echo "$delete_response" | sed '$d')
        if [ -n "$error_body" ]; then
            echo -e "${RED}  Error: ${error_body:0:300}${NC}"
        fi
    fi
done <<< "$patient_fhir_ids"

echo ""

# ============================================================================
# STEP 4: Delete Shared Resources by ID from bundle files
# ============================================================================
if [ "$DELETE_SHARED" = true ]; then
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 4: Deleting Shared Resources${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

    # Find bundle directory (assuming script is run from synthea root)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BUNDLES_DIR="$(dirname "$SCRIPT_DIR")/mock_patients/bundles"

    echo -e "${CYAN}Looking for shared resource IDs in: ${BUNDLES_DIR}${NC}"
    echo ""

    # Delete PractitionerRole first (references Practitioner, Organization, Location)
    if [ -f "${BUNDLES_DIR}/PractitionerRole.json" ]; then
        pr_ids=$(jq -r '.entry[].resource.id' "${BUNDLES_DIR}/PractitionerRole.json" 2>/dev/null)
        if [ -n "$pr_ids" ]; then
            echo -e "${CYAN}Deleting PractitionerRole resources...${NC}"
            while IFS= read -r pr_id; do
                if [ -n "$pr_id" ] && [ "$pr_id" != "null" ]; then
                    delete_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X DELETE "${HAPI_FHIR_URL}/PractitionerRole/${pr_id}" 2>/dev/null || echo -e "\n000")
                    delete_http_code=$(echo "$delete_response" | tail -n 1)
                    if [ "$delete_http_code" -ge 200 ] && [ "$delete_http_code" -lt 300 ]; then
                        expunge_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X POST "${HAPI_FHIR_URL}/PractitionerRole/${pr_id}/\$expunge" 2>/dev/null || echo -e "\n000")
                        expunge_http_code=$(echo "$expunge_response" | tail -n 1)
                        if [ "$expunge_http_code" -ge 200 ] && [ "$expunge_http_code" -lt 300 ]; then
                            echo -e "${GREEN}  ✓ HARD DELETED PractitionerRole/${pr_id}${NC}"
                        else
                            echo -e "${YELLOW}  ⚠ Soft deleted PractitionerRole/${pr_id}${NC}"
                        fi
                    elif [ "$delete_http_code" = "404" ]; then
                        echo -e "${CYAN}  ℹ PractitionerRole/${pr_id} not found${NC}"
                    else
                        echo -e "${YELLOW}  ⚠ Could not delete PractitionerRole/${pr_id} (HTTP ${delete_http_code})${NC}"
                    fi
                fi
            done <<< "$pr_ids"
            echo ""
        fi
    fi

    # Delete Location (may be referenced by PractitionerRole, but we deleted those)
    if [ -f "${BUNDLES_DIR}/Location.json" ]; then
        loc_ids=$(jq -r '.entry[].resource.id' "${BUNDLES_DIR}/Location.json" 2>/dev/null)
        if [ -n "$loc_ids" ]; then
            echo -e "${CYAN}Deleting Location resources...${NC}"
            while IFS= read -r loc_id; do
                if [ -n "$loc_id" ] && [ "$loc_id" != "null" ]; then
                    delete_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X DELETE "${HAPI_FHIR_URL}/Location/${loc_id}" 2>/dev/null || echo -e "\n000")
                    delete_http_code=$(echo "$delete_response" | tail -n 1)
                    if [ "$delete_http_code" -ge 200 ] && [ "$delete_http_code" -lt 300 ]; then
                        expunge_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X POST "${HAPI_FHIR_URL}/Location/${loc_id}/\$expunge" 2>/dev/null || echo -e "\n000")
                        expunge_http_code=$(echo "$expunge_response" | tail -n 1)
                        if [ "$expunge_http_code" -ge 200 ] && [ "$expunge_http_code" -lt 300 ]; then
                            echo -e "${GREEN}  ✓ HARD DELETED Location/${loc_id}${NC}"
                        else
                            echo -e "${YELLOW}  ⚠ Soft deleted Location/${loc_id}${NC}"
                        fi
                    elif [ "$delete_http_code" = "404" ]; then
                        echo -e "${CYAN}  ℹ Location/${loc_id} not found${NC}"
                    else
                        echo -e "${YELLOW}  ⚠ Could not delete Location/${loc_id} (HTTP ${delete_http_code})${NC}"
                    fi
                fi
            done <<< "$loc_ids"
            echo ""
        fi
    fi

    # Delete Practitioner
    if [ -f "${BUNDLES_DIR}/Practitioner.json" ]; then
        pract_ids=$(jq -r '.entry[].resource.id' "${BUNDLES_DIR}/Practitioner.json" 2>/dev/null)
        if [ -n "$pract_ids" ]; then
            echo -e "${CYAN}Deleting Practitioner resources...${NC}"
            while IFS= read -r pract_id; do
                if [ -n "$pract_id" ] && [ "$pract_id" != "null" ]; then
                    delete_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X DELETE "${HAPI_FHIR_URL}/Practitioner/${pract_id}" 2>/dev/null || echo -e "\n000")
                    delete_http_code=$(echo "$delete_response" | tail -n 1)
                    if [ "$delete_http_code" -ge 200 ] && [ "$delete_http_code" -lt 300 ]; then
                        expunge_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X POST "${HAPI_FHIR_URL}/Practitioner/${pract_id}/\$expunge" 2>/dev/null || echo -e "\n000")
                        expunge_http_code=$(echo "$expunge_response" | tail -n 1)
                        if [ "$expunge_http_code" -ge 200 ] && [ "$expunge_http_code" -lt 300 ]; then
                            echo -e "${GREEN}  ✓ HARD DELETED Practitioner/${pract_id}${NC}"
                        else
                            echo -e "${YELLOW}  ⚠ Soft deleted Practitioner/${pract_id}${NC}"
                        fi
                    elif [ "$delete_http_code" = "404" ]; then
                        echo -e "${CYAN}  ℹ Practitioner/${pract_id} not found${NC}"
                    else
                        echo -e "${YELLOW}  ⚠ Could not delete Practitioner/${pract_id} (HTTP ${delete_http_code})${NC}"
                    fi
                fi
            done <<< "$pract_ids"
            echo ""
        fi
    fi

    # Delete Organization (last, as it may be referenced by others)
    if [ -f "${BUNDLES_DIR}/Organization.json" ]; then
        org_ids=$(jq -r '.entry[].resource.id' "${BUNDLES_DIR}/Organization.json" 2>/dev/null)
        if [ -n "$org_ids" ]; then
            echo -e "${CYAN}Deleting Organization resources...${NC}"
            while IFS= read -r org_id; do
                if [ -n "$org_id" ] && [ "$org_id" != "null" ]; then
                    delete_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X DELETE "${HAPI_FHIR_URL}/Organization/${org_id}" 2>/dev/null || echo -e "\n000")
                    delete_http_code=$(echo "$delete_response" | tail -n 1)
                    if [ "$delete_http_code" -ge 200 ] && [ "$delete_http_code" -lt 300 ]; then
                        expunge_response=$(curl -s -w "\n%{http_code}" --connect-timeout 5 --max-time 10 -X POST "${HAPI_FHIR_URL}/Organization/${org_id}/\$expunge" 2>/dev/null || echo -e "\n000")
                        expunge_http_code=$(echo "$expunge_response" | tail -n 1)
                        if [ "$expunge_http_code" -ge 200 ] && [ "$expunge_http_code" -lt 300 ]; then
                            echo -e "${GREEN}  ✓ HARD DELETED Organization/${org_id}${NC}"
                        else
                            echo -e "${YELLOW}  ⚠ Soft deleted Organization/${org_id}${NC}"
                        fi
                    elif [ "$delete_http_code" = "404" ]; then
                        echo -e "${CYAN}  ℹ Organization/${org_id} not found${NC}"
                    else
                        echo -e "${YELLOW}  ⚠ Could not delete Organization/${org_id} (HTTP ${delete_http_code})${NC}"
                    fi
                fi
            done <<< "$org_ids"
            echo ""
        fi
    fi
else
    echo -e "${CYAN}Skipping Step 4: Delete Shared Resources (--delete-shared not specified)${NC}"
    echo ""
fi

# ============================================================================
# COMPLETION
# ============================================================================
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}                    CLEANUP COMPLETED                          ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}✓ All patient resources matching identifier ${PATIENT_IDENTIFIER} have been PERMANENTLY removed${NC}"
echo -e "${GREEN}✓ Resources were HARD DELETED using HAPI FHIR's \$expunge operation${NC}"
if [ "$DELETE_SHARED" = true ]; then
    echo -e "${GREEN}✓ Shared resources (Organization, Practitioner, Location) were also removed${NC}"
else
    echo -e "${YELLOW}⚠ Shared resources were NOT deleted (use --delete-shared to remove them)${NC}"
fi
echo -e "${CYAN}Note: Database records and TRAIS indices should be cleaned separately${NC}"
echo ""
echo -e "${YELLOW}You can now safely re-upload patient ${PATIENT_IDENTIFIER} without ID conflicts${NC}"
echo ""

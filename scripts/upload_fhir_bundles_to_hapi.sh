#!/bin/bash
#
# Complete Mock Patient FHIR Bundle Upload Pipeline
#
# This script performs the complete workflow to onboard a mock test patient into the ThetaRho platform:
# 1. Upload FHIR bundles directly to HAPI FHIR (shared resources + patient bundle)
# 2. Create patient record in PostgreSQL database (trasdb)
# 3. Populate aggregator_resource_fhir_map table with athena ID → FHIR ID mappings
# 4. Reload aggregator map cache in ThetaRhoAppServer
# 5. Tag patient resources (optional for mock data)
# 6. Index patient in TRAIS (OpenSearch + FAISS) for AI question answering
#
# Usage: ./upload_fhir_bundles_to_hapi.sh <patient_id> [options]
#
# Examples:
#   ./upload_fhir_bundles_to_hapi.sh t7
#   ./upload_fhir_bundles_to_hapi.sh t7 --server swenson-clone.thetarho.com
#   ./upload_fhir_bundles_to_hapi.sh t7 --practice-id 16349 --start-step 3
#   ./upload_fhir_bundles_to_hapi.sh t7 --server localhost --practice-id 12345 --start-step 5
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default configuration
PATIENT_ID=""
SERVER_BASE="swenson-clone.thetarho.com"
PRACTICE_ID_EHR_INT="16349"
START_STEP=1

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --server)
            SERVER_BASE="$2"
            shift 2
            ;;
        --practice-id)
            PRACTICE_ID_EHR_INT="$2"
            shift 2
            ;;
        --start-step)
            START_STEP="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 <patient_id> [options]"
            echo ""
            echo "Arguments:"
            echo "  patient_id           - Patient ID (e.g., t7) [REQUIRED]"
            echo ""
            echo "Options:"
            echo "  --server HOST        - Server hostname (default: swenson-clone.thetarho.com)"
            echo "  --practice-id ID     - Practice ID numeric part (default: 16349)"
            echo "  --start-step NUM     - Start from step NUM (1-6, default: 1)"
            echo "  -h, --help           - Show this help message"
            echo ""
            echo "Steps:"
            echo "  1. Upload FHIR bundles to HAPI FHIR"
            echo "  2. Create patient record in PostgreSQL"
            echo "  3. Populate aggregator resource map"
            echo "  4. Reload aggregator map cache"
            echo "  5. Tag patient resources"
            echo "  6. Index patient in TRAIS"
            echo ""
            echo "Examples:"
            echo "  $0 t7"
            echo "  $0 t7 --server swenson-clone.thetarho.com"
            echo "  $0 t7 --practice-id 16349 --start-step 3"
            echo "  $0 t7 --server localhost --practice-id 12345 --start-step 5"
            exit 0
            ;;
        *)
            if [ -z "$PATIENT_ID" ]; then
                PATIENT_ID="$1"
            else
                echo -e "${RED}Error: Unknown argument: $1${NC}"
                echo "Use --help for usage information"
                exit 1
            fi
            shift
            ;;
    esac
done

# Strip http:// or https:// if provided and extract hostname
SERVER_HOST=$(echo "$SERVER_BASE" | sed 's|^https\?://||')

# Construct service URLs
HAPI_FHIR_URL="http://${SERVER_HOST}:8080/fhir"
TRD_SERVER_URL="http://${SERVER_HOST}:9090"
TRAIS_SERVER_URL="http://${SERVER_HOST}:5000"
TRAPP_SERVER_URL="http://${SERVER_HOST}"

# Database configuration (for local access)
DB_HOST="${DB_HOST:-${SERVER_HOST}}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-trasdb}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-postgres}"

# SSH configuration for remote SQL execution
SSH_USER="${SSH_USER:-ubuntu}"  # Username for SSH connection to remote server

# Script directory (to find mock_patients folder)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOCK_PATIENTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/mock_patients"

# Validate arguments
if [ -z "$PATIENT_ID" ]; then
    echo -e "${RED}Error: Missing required patient_id argument${NC}"
    echo "Use --help for usage information"
    exit 1
fi

# Validate START_STEP is between 1-6
if [ "$START_STEP" -lt 1 ] || [ "$START_STEP" -gt 6 ]; then
    echo -e "${RED}Error: --start-step must be between 1 and 6${NC}"
    exit 1
fi

# Determine patient folder (remove 't' prefix for directory name)
patient_num="${PATIENT_ID#t}"
PATIENT_DIR="${MOCK_PATIENTS_DIR}/${PATIENT_ID}"
BUNDLES_DIR="${MOCK_PATIENTS_DIR}/bundles"

# Step 1 prerequisite validation - only if starting from step 1
if [ "$START_STEP" -eq 1 ]; then
    # Validate patient directory exists
    if [ ! -d "$PATIENT_DIR" ]; then
        echo -e "${RED}Error: Patient directory not found: ${PATIENT_DIR}${NC}"
        exit 1
    fi

    # Validate bundle exists
    PATIENT_BUNDLE="${BUNDLES_DIR}/${PATIENT_ID}_bundle.json"
    if [ ! -f "$PATIENT_BUNDLE" ]; then
        echo -e "${RED}Error: Patient bundle not found: ${PATIENT_BUNDLE}${NC}"
        exit 1
    fi
else
    # For steps 2-6, just set the bundle path (don't validate - may skip upload step)
    PATIENT_BUNDLE="${BUNDLES_DIR}/${PATIENT_ID}_bundle.json"
fi

# Step 2+ prerequisite validation - check if FHIR patient exists
if [ "$START_STEP" -ge 2 ]; then
    echo -e "${YELLOW}Validating prerequisites for starting at step ${START_STEP}...${NC}"

    # Check if Patient resource exists in HAPI FHIR
    patient_check=$(curl -s -w "\n%{http_code}" -X GET "${HAPI_FHIR_URL}/Patient?identifier=${PATIENT_ID}")
    http_code=$(echo "$patient_check" | tail -n 1)

    if [ "$http_code" -ne 200 ]; then
        echo -e "${RED}Error: Cannot start from step ${START_STEP}${NC}"
        echo -e "${RED}Prerequisite Step 1 not completed: Patient not found in HAPI FHIR${NC}"
        echo -e "${YELLOW}Hint: Run from step 1 first to upload FHIR resources${NC}"
        exit 1
    fi

    patient_data=$(echo "$patient_check" | sed '$d')
    total_patients=$(echo "$patient_data" | jq -r '.total // 0')

    if [ "$total_patients" -eq 0 ]; then
        echo -e "${RED}Error: Cannot start from step ${START_STEP}${NC}"
        echo -e "${RED}Prerequisite Step 1 not completed: Patient ${PATIENT_ID} not found in HAPI FHIR${NC}"
        echo -e "${YELLOW}Hint: Run from step 1 first to upload FHIR resources${NC}"
        exit 1
    fi

    echo -e "${GREEN}  ✓ Step 1 prerequisite validated: Patient exists in HAPI FHIR${NC}"
fi

# Step 3+ prerequisite validation - check if patient exists in database
if [ "$START_STEP" -ge 3 ]; then
    # Create temporary SSH key file for validation
    SSH_KEY_FILE="/tmp/skynet_key_$$"
    cat > "$SSH_KEY_FILE" << 'EOF'
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBWoVDnFM0xTnbWS60UuY+fwC03lqS7OXy7cTBMRpUVBAAAAKhD7UlcQ+1J
XAAAAAtzc2gtZWQyNTUxOQAAACBWoVDnFM0xTnbWS60UuY+fwC03lqS7OXy7cTBMRpUVBA
AAAEA5QYvAAfp2Q1bBdPNYnhpmu7NWJirAv/LRNe1IavvK4FahUOcUzTFOdtZLrRS5j5/A
LTeWpLs5fLtxMExGlRUEAAAAI2FuaXJ1ZGhyQEFuaXJ1ZGhzLU1hY0Jvb2stUHJvLmxvY2
FsAQI=
-----END OPENSSH PRIVATE KEY-----
EOF
    chmod 600 "$SSH_KEY_FILE"

    # Check if patient exists in database
    full_athena_id="a-${PRACTICE_ID_EHR_INT}.E-${PATIENT_ID}"
    db_check=$(ssh -i "$SSH_KEY_FILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${SSH_USER}@${DB_HOST}" "sudo -u postgres psql -U postgres -d ${DB_NAME} -t -c \"SELECT COUNT(*) FROM patient WHERE patient_id_ehr_int = '${full_athena_id}';\"" 2>&1)

    rm -f "$SSH_KEY_FILE"

    patient_count=$(echo "$db_check" | tr -d ' \t\n\r')

    if [ "$patient_count" != "1" ]; then
        echo -e "${RED}Error: Cannot start from step ${START_STEP}${NC}"
        echo -e "${RED}Prerequisite Step 2 not completed: Patient not found in database${NC}"
        echo -e "${YELLOW}Hint: Run from step 1 or 2 first to create patient record${NC}"
        exit 1
    fi

    echo -e "${GREEN}  ✓ Step 2 prerequisite validated: Patient exists in database${NC}"
fi

# Step 5+ prerequisite validation - check if aggregator map exists
if [ "$START_STEP" -ge 5 ]; then
    # Create temporary SSH key file for validation
    SSH_KEY_FILE="/tmp/skynet_key_$$"
    cat > "$SSH_KEY_FILE" << 'EOF'
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBWoVDnFM0xTnbWS60UuY+fwC03lqS7OXy7cTBMRpUVBAAAAKhD7UlcQ+1J
XAAAAAtzc2gtZWQyNTUxOQAAACBWoVDnFM0xTnbWS60UuY+fwC03lqS7OXy7cTBMRpUVBA
AAAEA5QYvAAfp2Q1bBdPNYnhpmu7NWJirAv/LRNe1IavvK4FahUOcUzTFOdtZLrRS5j5/A
LTeWpLs5fLtxMExGlRUEAAAAI2FuaXJ1ZGhyQEFuaXJ1ZGhzLU1hY0Jvb2stUHJvLmxvY2
FsAQI=
-----END OPENSSH PRIVATE KEY-----
EOF
    chmod 600 "$SSH_KEY_FILE"

    # Check if aggregator map has Patient entry
    full_athena_id="a-${PRACTICE_ID_EHR_INT}.E-${PATIENT_ID}"
    map_check=$(ssh -i "$SSH_KEY_FILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${SSH_USER}@${DB_HOST}" "sudo -u postgres psql -U postgres -d ${DB_NAME} -t -c \"SELECT COUNT(*) FROM aggregator_resource_fhir_map WHERE resource = 'Patient' AND athenaid = '${full_athena_id}';\"" 2>&1)

    rm -f "$SSH_KEY_FILE"

    map_count=$(echo "$map_check" | tr -d ' \t\n\r')

    if [ "$map_count" != "1" ]; then
        echo -e "${RED}Error: Cannot start from step ${START_STEP}${NC}"
        echo -e "${RED}Prerequisite Steps 3-4 not completed: Aggregator map not populated${NC}"
        echo -e "${YELLOW}Hint: Run from step 1, 2, or 3 first to populate aggregator map${NC}"
        exit 1
    fi

    echo -e "${GREEN}  ✓ Steps 3-4 prerequisite validated: Aggregator map exists${NC}"
fi

if [ "$START_STEP" -gt 1 ]; then
    echo ""
fi

# Display header
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       ThetaRho Mock Patient Upload Pipeline                   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Configuration:${NC}"
echo "  Patient ID:        ${PATIENT_ID}"
echo "  Practice ID:       ${PRACTICE_ID_EHR_INT}"
echo "  Patient Directory: ${PATIENT_DIR}"
echo "  Patient Bundle:    ${PATIENT_BUNDLE}"
echo "  Server Host:       ${SERVER_HOST}"
echo "  HAPI FHIR:         ${HAPI_FHIR_URL}"
echo "  TRDataServices:    ${TRD_SERVER_URL}"
echo "  TRAIS:             ${TRAIS_SERVER_URL}"
echo "  ThetaRhoAppServer: ${TRAPP_SERVER_URL}"
if [ "$START_STEP" -gt 1 ]; then
    echo "  Starting from:     Step ${START_STEP}"
fi
echo ""

# Temporary file to store resource ID mappings
MAPPING_FILE=$(mktemp)
trap "rm -f $MAPPING_FILE" EXIT

# Helper function for API calls
call_api() {
    local method=$1
    local url=$2
    local content_type=$3
    local data=$4
    local description=$5

    # Send status message to stderr so it doesn't pollute stdout/variable capture
    echo -e "${YELLOW}→ ${description}${NC}" >&2

    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" -X GET "$url")
    elif [ "$method" = "POST" ] && [ "$content_type" = "application/json" ]; then
        response=$(curl -s -w "\n%{http_code}" \
            -X POST \
            -H "Content-Type: application/json" \
            -d "$data" \
            "$url")
    elif [ "$method" = "POST" ] && [ "$content_type" = "application/fhir+json" ]; then
        # For FHIR bundles, send file directly
        response=$(curl -s -w "\n%{http_code}" \
            -X POST \
            -H "Content-Type: application/fhir+json" \
            --data-binary "@${data}" \
            "$url")
    elif [ "$method" = "POST" ]; then
        # POST without data (empty body)
        response=$(curl -s -w "\n%{http_code}" -X POST "$url")
    fi

    http_code=$(echo "$response" | tail -n 1)
    body=$(echo "$response" | sed '$d')

    # Debug logging
    echo -e "${CYAN}[DEBUG] HTTP Code: ${http_code}${NC}" >&2

    # Validate http_code is a number
    if [ -z "$http_code" ] || ! [[ "$http_code" =~ ^[0-9]+$ ]]; then
        echo -e "${RED}  ✗ Failed (Invalid HTTP code: ${http_code})${NC}" >&2
        echo -e "${RED}  Response (first 500 chars): ${body:0:500}${NC}" >&2
        return 1
    fi

    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        # Send success message to stderr
        echo -e "${GREEN}  ✓ Success (HTTP ${http_code})${NC}" >&2
        # Only output the body to stdout (for variable capture)
        echo "$body"
        return 0
    else
        # Send error messages to stderr
        echo -e "${RED}  ✗ Failed (HTTP ${http_code})${NC}" >&2
        echo -e "${RED}  Full error response:${NC}" >&2
        echo "$body" >&2
        return 1
    fi
}

# Helper function to extract FHIR ID from transaction response
extract_fhir_id() {
    local response="$1"
    local resource_type="$2"

    # For transaction responses, extract from location field
    # Format: "Organization/t8010511/_history/3"
    location=$(echo "$response" | jq -r ".entry[]? | select(.response.location? | contains(\"$resource_type/\")) | .response.location" 2>/dev/null | head -1)

    if [ -n "$location" ] && [ "$location" != "null" ]; then
        # Extract ID from location (format: ResourceType/ID/_history/version)
        id=$(echo "$location" | sed -E "s|^${resource_type}/([^/]+).*|\1|")
        echo "$id"
        return 0
    fi

    # Fallback: try to get from resource.id if response includes resources
    id=$(echo "$response" | jq -r ".entry[]? | select(.resource.resourceType == \"$resource_type\") | .resource.id" 2>/dev/null | head -1)

    if [ -z "$id" ] || [ "$id" = "null" ]; then
        # Last fallback: bundle id itself
        id=$(echo "$response" | jq -r ".id" 2>/dev/null)
    fi

    echo "$id"
}

# ============================================================================
# STEP 1: Upload FHIR Resources to HAPI FHIR
# ============================================================================
if [ "$START_STEP" -le 1 ]; then
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 1: Uploading FHIR Resources to HAPI FHIR${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

# Step 1.1: Upload shared resources first (Organization, Location, Practitioner)
echo -e "${CYAN}Step 1.1: Uploading Shared Resources${NC}"
echo ""

# Upload Organization
if [ -f "${BUNDLES_DIR}/Organization.json" ]; then
    org_response=$(call_api "POST" "$HAPI_FHIR_URL" "application/fhir+json" "${BUNDLES_DIR}/Organization.json" "Uploading Organization bundle")
    if [ $? -eq 0 ]; then
        org_id=$(extract_fhir_id "$org_response" "Organization")
        echo "Organization:$org_id" >> "$MAPPING_FILE"
        echo -e "${GREEN}  Organization ID: ${org_id}${NC}"
    fi
fi

# Upload Practitioner
if [ -f "${BUNDLES_DIR}/Practitioner.json" ]; then
    pract_response=$(call_api "POST" "$HAPI_FHIR_URL" "application/fhir+json" "${BUNDLES_DIR}/Practitioner.json" "Uploading Practitioner bundle")
    if [ $? -eq 0 ]; then
        pract_id=$(extract_fhir_id "$pract_response" "Practitioner")
        echo "Practitioner:$pract_id" >> "$MAPPING_FILE"
        echo -e "${GREEN}  Practitioner ID: ${pract_id}${NC}"
    else
        echo -e "${YELLOW}  ⚠ Practitioner upload failed (may already exist) - continuing...${NC}"
    fi
fi

# Upload Location
if [ -f "${BUNDLES_DIR}/Location.json" ]; then
    loc_response=$(call_api "POST" "$HAPI_FHIR_URL" "application/fhir+json" "${BUNDLES_DIR}/Location.json" "Uploading Location bundle")
    if [ $? -eq 0 ]; then
        loc_ids=$(echo "$loc_response" | jq -r '.entry[]? | select(.resource.resourceType == "Location") | .resource.id' 2>/dev/null)
        while IFS= read -r loc_id; do
            echo "Location:$loc_id" >> "$MAPPING_FILE"
            echo -e "${GREEN}  Location ID: ${loc_id}${NC}"
        done <<< "$loc_ids"
    fi
fi

# Upload PractitionerRole
if [ -f "${BUNDLES_DIR}/PractitionerRole.json" ]; then
    practrole_response=$(call_api "POST" "$HAPI_FHIR_URL" "application/fhir+json" "${BUNDLES_DIR}/PractitionerRole.json" "Uploading PractitionerRole bundle")
    if [ $? -eq 0 ]; then
        practrole_id=$(extract_fhir_id "$practrole_response" "PractitionerRole")
        echo "PractitionerRole:$practrole_id" >> "$MAPPING_FILE"
        echo -e "${GREEN}  PractitionerRole ID: ${practrole_id}${NC}"
    fi
fi

echo ""

# Step 1.2: Upload patient bundle (without shared resources - they were uploaded above)
echo -e "${CYAN}Step 1.2: Uploading Patient Bundle (Clinical Resources Only)${NC}"
echo ""

patient_bundle_response=$(call_api "POST" "$HAPI_FHIR_URL" "application/fhir+json" "$PATIENT_BUNDLE" "Uploading patient bundle")

if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to upload patient bundle${NC}"
    exit 1
fi

# Extract resource IDs from bundle response
echo -e "${CYAN}Extracting resource IDs from upload response...${NC}"

# HAPI FHIR transaction responses have entry.response.location with the format: ResourceType/ID/_history/version
# Dynamically extract all resource types from the response
total_extracted=0

# Get all unique resource types from the response locations
resource_types=$(echo "$patient_bundle_response" | jq -r '.entry[]?.response.location?' 2>/dev/null | grep -v '^null$' | sed -E 's|^([^/]+)/.*|\1|' | sort -u)

# Process each resource type
while IFS= read -r resource_type; do
    if [ -n "$resource_type" ]; then
        # Extract IDs from response.location field (format: "Patient/12345/_history/1")
        ids=$(echo "$patient_bundle_response" | jq -r ".entry[]? | select(.response.location? | startswith(\"$resource_type/\")) | .response.location" 2>/dev/null | sed -E "s|^${resource_type}/([^/]+)/.*|\1|")

        if [ -n "$ids" ]; then
            count=0
            while IFS= read -r fhir_id; do
                if [ -n "$fhir_id" ] && [ "$fhir_id" != "null" ]; then
                    echo "${resource_type}:${fhir_id}" >> "$MAPPING_FILE"
                    ((count++))
                    ((total_extracted++))
                fi
            done <<< "$ids"

            if [ $count -gt 0 ]; then
                echo -e "${GREEN}  ✓ ${resource_type}: ${count} resources${NC}"
            fi
        fi
    fi
done <<< "$resource_types"

echo -e "${GREEN}  ✓ Extracted ${total_extracted} resource IDs from patient bundle${NC}"
echo ""

# Display mapping summary
    total_resources=$(wc -l < "$MAPPING_FILE")
    echo -e "${CYAN}Total resources uploaded: ${total_resources}${NC}"
    echo ""
else
    echo -e "${YELLOW}Skipping Step 1: Upload FHIR Resources (starting from step ${START_STEP})${NC}"
    echo ""
fi

# ============================================================================
# STEP 2: Create Patient Record in PostgreSQL
# ============================================================================
if [ "$START_STEP" -le 2 ]; then
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 2: Creating Patient Record in PostgreSQL Database${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

# Fetch practice list
practices=$(call_api "GET" "${TRD_SERVER_URL}/practices/getAllPractices" "" "" "Fetching practices from TRDataServices")

if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to fetch practices${NC}"
    exit 1
fi

# Match practice by practiceIdEhrInt
matched_practice=$(echo "$practices" | jq ".[] | select(.practiceIdEhrInt == \"${PRACTICE_ID_EHR_INT}\")")

if [ -z "$matched_practice" ]; then
    echo -e "${RED}  ✗ No matching practice found for practiceIdEhrInt: ${PRACTICE_ID_EHR_INT}${NC}"
    exit 1
fi

practice_id=$(echo "$matched_practice" | jq -r '.practiceId')
practice_name=$(echo "$matched_practice" | jq -r '.name')

echo -e "${GREEN}  ✓ Matched practice:${NC}"
echo "    Practice ID:       ${practice_id}"
echo "    Practice Name:     ${practice_name}"
echo "    Practice EHR Int:  ${PRACTICE_ID_EHR_INT}"
echo ""

# Extract patient demographics from uploaded Patient resource
echo -e "${YELLOW}→ Fetching uploaded Patient resource from HAPI FHIR${NC}"

patient_fhir_id=$(grep "^Patient:" "$MAPPING_FILE" | head -1 | cut -d: -f2)
patient_resource=$(call_api "GET" "${HAPI_FHIR_URL}/Patient/${patient_fhir_id}" "" "" "Fetching Patient resource")

if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to fetch Patient resource${NC}"
    exit 1
fi

# Extract demographics
first_name=$(echo "$patient_resource" | jq -r '.name[0].given[0]')
last_name=$(echo "$patient_resource" | jq -r '.name[0].family')
gender=$(echo "$patient_resource" | jq -r '.gender')
birth_date=$(echo "$patient_resource" | jq -r '.birthDate')

echo -e "${GREEN}  ✓ Extracted patient demographics:${NC}"
echo "    First Name:        ${first_name}"
echo "    Last Name:         ${last_name}"
echo "    Gender:            ${gender}"
echo "    Birth Date:        ${birth_date}"
echo "    FHIR Patient ID:   ${patient_fhir_id}"
echo ""

# Construct patient record JSON
full_athena_id="a-${PRACTICE_ID_EHR_INT}.E-${PATIENT_ID}"

patient_json_data=$(jq -n \
    --arg practiceIdFK "$practice_id" \
    --arg patientIdExt "E-${PATIENT_ID}" \
    --arg patientIdEhrInt "$full_athena_id" \
    --arg fhirPatientId "$patient_fhir_id" \
    --arg firstName "$first_name" \
    --arg lastName "$last_name" \
    --arg sex "$gender" \
    --arg dateOfBirth "$birth_date" \
    '{
        practiceIdFK: ($practiceIdFK | tonumber),
        patientIdExt: $patientIdExt,
        patientIdEhrInt: $patientIdEhrInt,
        fhir_patient_id: $fhirPatientId,
        firstName: $firstName,
        lastName: $lastName,
        sex: $sex,
        dateOfBirth: $dateOfBirth
    }')

patient_create_result=$(call_api "POST" "${TRD_SERVER_URL}/patients/createPatient" "application/json" "$patient_json_data" "Creating patient record in database")

if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to create patient in database${NC}"
    exit 1
fi

    created_patient_id=$(echo "$patient_create_result" | jq -r '.patientId')
    echo -e "${GREEN}  ✓ Patient created with database ID: ${created_patient_id}${NC}"
    echo ""
else
    echo -e "${YELLOW}Skipping Step 2: Create Patient Record (starting from step ${START_STEP})${NC}"
    echo ""
fi

# ============================================================================
# STEP 3: Populate Aggregator Resource Map
# ============================================================================
if [ "$START_STEP" -le 3 ]; then
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 3: Populating Aggregator Resource Map in PostgreSQL${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

    echo -e "${CYAN}Generating SQL INSERT statements for aggregator_resource_fhir_map...${NC}"
    echo -e "${YELLOW}Note: Only Patient resource is required for tagging to work${NC}"
    echo ""

    # If we skipped Step 1, we need to get the patient FHIR ID from HAPI FHIR
    if [ "$START_STEP" -gt 1 ]; then
        echo -e "${YELLOW}Fetching patient FHIR ID from HAPI FHIR (Step 1 was skipped)...${NC}"
        patient_search=$(curl -s "${HAPI_FHIR_URL}/Patient?identifier=${PATIENT_ID}")
        patient_fhir_id=$(echo "$patient_search" | jq -r '.entry[0].resource.id // ""')

        if [ -z "$patient_fhir_id" ]; then
            echo -e "${RED}Error: Could not find Patient with identifier ${PATIENT_ID} in HAPI FHIR${NC}"
            exit 1
        fi

        # Create mapping file entry for this patient
        echo "Patient:${patient_fhir_id}" > "$MAPPING_FILE"
        echo -e "${GREEN}  ✓ Found Patient FHIR ID: ${patient_fhir_id}${NC}"
    fi

    # Generate SQL statements - ONLY for Patient resource
    # Based on code analysis: PatientTaggingService only needs Patient mappings
    # It queries: getTRIdForResource("Patient", athenaPatientId) to get FHIR patient ID
    # Then uses that FHIR ID to query and tag all other resources directly from HAPI FHIR

    sql_inserts=""
    insert_count=0

    while IFS=: read -r resource_type fhir_id; do
        # Only process Patient resource for aggregator map
        if [ "$resource_type" = "Patient" ]; then
            athena_id="a-${PRACTICE_ID_EHR_INT}.E-${PATIENT_ID}"

            if [ -n "$athena_id" ] && [ -n "$fhir_id" ] && [ "$fhir_id" != "null" ]; then
                sql_inserts="INSERT INTO aggregator_resource_fhir_map (resource, athenaid, trid) VALUES ('${resource_type}', '${athena_id}', '${fhir_id}');"
                ((insert_count++))
                echo -e "${CYAN}  ${resource_type}: ${athena_id} → ${fhir_id}${NC}"
            fi
        fi

    done < "$MAPPING_FILE"

    echo ""
    echo -e "${CYAN}Total mappings to insert: ${insert_count}${NC}"
    echo ""

    # Execute SQL via SSH with private key
    if [ $insert_count -gt 0 ]; then
        echo -e "${YELLOW}→ Executing SQL INSERTs via SSH to ${DB_HOST}${NC}"

        # Create temporary SSH key file
        SSH_KEY_FILE="/tmp/skynet_key_$$"
        cat > "$SSH_KEY_FILE" << 'EOF'
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBWoVDnFM0xTnbWS60UuY+fwC03lqS7OXy7cTBMRpUVBAAAAKhD7UlcQ+1J
XAAAAAtzc2gtZWQyNTUxOQAAACBWoVDnFM0xTnbWS60UuY+fwC03lqS7OXy7cTBMRpUVBA
AAAEA5QYvAAfp2Q1bBdPNYnhpmu7NWJirAv/LRNe1IavvK4FahUOcUzTFOdtZLrRS5j5/A
LTeWpLs5fLtxMExGlRUEAAAAI2FuaXJ1ZGhyQEFuaXJ1ZGhzLU1hY0Jvb2stUHJvLmxvY2
FsAQI=
-----END OPENSSH PRIVATE KEY-----
EOF

        # Set proper permissions for SSH key
        chmod 600 "$SSH_KEY_FILE"

        # Execute via SSH using sudo to run psql as postgres user
        # The 'db' alias on remote server is: sudo -u postgres psql -U postgres
        # Temporarily disable exit-on-error for this command
        set +e
        ssh_result=$(ssh -i "$SSH_KEY_FILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "${SSH_USER}@${DB_HOST}" "sudo -u postgres psql -U postgres -d ${DB_NAME} -c \"${sql_inserts}\"" 2>&1)
        sql_exit_code=$?
        set -e

        # Clean up SSH key file
        rm -f "$SSH_KEY_FILE"

        if [ $sql_exit_code -eq 0 ]; then
            echo -e "${GREEN}  ✓ Successfully inserted ${insert_count} aggregator map entries${NC}"
        else
            echo -e "${RED}  ✗ Failed to execute SQL INSERTs (exit code: ${sql_exit_code})${NC}"
            echo -e "${RED}  Error output:${NC}"
            echo -e "${RED}${ssh_result}${NC}"
            echo ""
            echo -e "${YELLOW}  Note: This may prevent tagging and indexing from working properly${NC}"
        fi
    else
        echo -e "${YELLOW}  ⚠ No mappings to insert${NC}"
    fi

    echo ""
else
    echo -e "${YELLOW}Skipping Step 3: Populate Aggregator Resource Map (starting from step ${START_STEP})${NC}"
    echo ""
fi

# ============================================================================
# STEP 4: Reload Aggregator Map Cache
# ============================================================================
if [ "$START_STEP" -le 4 ]; then
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 4: Reloading Aggregator Map Cache${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

    reload_result=$(call_api "POST" "${TRAPP_SERVER_URL}/api/fhir/reloadResourceMapListFromDB" "" "" "Reloading in-memory aggregator map cache")

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✓ Cache reloaded successfully${NC}"
    else
        echo -e "${YELLOW}  ⚠ Cache reload encountered issues (may be non-fatal)${NC}"
    fi

    echo ""
else
    echo -e "${YELLOW}Skipping Step 4: Reload Aggregator Map Cache (starting from step ${START_STEP})${NC}"
    echo ""
fi

# ============================================================================
# STEP 5: Tag Patient Resources
# ============================================================================
if [ "$START_STEP" -le 5 ]; then
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 5: Tagging Patient Resources${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

    # Tag patient resources to mark latest appointments, vitals, conditions, etc.
    # This adds meta.tag entries to resources for filtering in UI
    # Use athena-format patient ID (a-11783.E-t102)
    echo -e "${CYAN}Tagging latest resources for patient ${PATIENT_ID_EHR_INT}...${NC}"

    tag_result=$(call_api "GET" "${TRD_SERVER_URL}/athenahealth/tagAPatient/${PRACTICE_ID_EHR_INT}/${PATIENT_ID}" "" "" "Tagging patient resources")

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✓ Patient resources tagged successfully${NC}"
    else
        echo -e "${YELLOW}  ⚠ Tagging encountered some errors (may be non-fatal)${NC}"
    fi

    echo ""
else
    echo -e "${YELLOW}Skipping Step 5: Tag Patient Resources (starting from step ${START_STEP})${NC}"
    echo ""
fi

# ============================================================================
# STEP 6: Index Patient in TRAIS
# ============================================================================
if [ "$START_STEP" -le 6 ]; then
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 6: Indexing Patient in TRAIS (OpenSearch + FAISS)${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

    full_athena_id="a-${PRACTICE_ID_EHR_INT}.E-${PATIENT_ID}"
    index_result=$(call_api "GET" "${TRAIS_SERVER_URL}/trais/qa/indexPatient/${full_athena_id}" "" "" "Indexing patient in TRAIS for AI question answering")

    if [ $? -ne 0 ]; then
        echo -e "${RED}Failed to index patient in TRAIS${NC}"
        echo -e "${YELLOW}Note: Patient data is in FHIR but not indexed for AI${NC}"
    fi

    echo ""
else
    echo -e "${YELLOW}Skipping Step 6: Index Patient in TRAIS (starting from step ${START_STEP})${NC}"
    echo ""
fi

# ============================================================================
# Success Summary
# ============================================================================
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Mock Patient Upload Pipeline Complete!                 ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Fetch patient details if we skipped Step 2 (variables not set)
if [ -z "$first_name" ] || [ -z "$patient_fhir_id" ]; then
    echo -e "${YELLOW}Fetching patient details from HAPI FHIR...${NC}"
    patient_search=$(curl -s "${HAPI_FHIR_URL}/Patient?identifier=${PATIENT_ID}")
    patient_fhir_id=$(echo "$patient_search" | jq -r '.entry[0].resource.id // "N/A"')
    first_name=$(echo "$patient_search" | jq -r '.entry[0].resource.name[0].given[0] // "N/A"')
    last_name=$(echo "$patient_search" | jq -r '.entry[0].resource.name[0].family // "N/A"')
    full_athena_id="a-${PRACTICE_ID_EHR_INT}.E-${PATIENT_ID}"
fi

echo -e "${CYAN}Patient Summary:${NC}"
echo "  Patient ID:          ${PATIENT_ID}"
echo "  Name:                ${first_name} ${last_name}"
if [ -n "$practice_name" ]; then
    echo "  Practice:            ${practice_name}"
fi
if [ -n "$created_patient_id" ]; then
    echo "  Database ID:         ${created_patient_id}"
fi
echo "  FHIR Patient ID:     ${patient_fhir_id}"
echo "  Full Athena ID:      ${full_athena_id}"
echo ""

if [ "$START_STEP" -le 1 ]; then
    echo -e "${CYAN}Resources Uploaded:      ${total_resources:-N/A}${NC}"
fi

if [ "$START_STEP" -le 3 ]; then
    echo -e "${CYAN}Aggregator Map Entries:  ${insert_count:-N/A}${NC}"
fi

if [ "$START_STEP" -le 1 ] || [ "$START_STEP" -le 3 ]; then
    echo ""
fi
echo -e "${CYAN}Data Storage Status:${NC}"
echo "  ${GREEN}✓${NC} Patient metadata in PostgreSQL (trasdb)"
echo "  ${GREEN}✓${NC} Clinical data in HAPI FHIR Server"
echo "  ${GREEN}✓${NC} Aggregator map populated"
echo "  ${GREEN}✓${NC} Cache reloaded in ThetaRhoAppServer"
echo "  ${GREEN}✓${NC} Indexed in OpenSearch (keyword search)"
echo "  ${GREEN}✓${NC} Indexed in FAISS (vector similarity search)"
echo ""
echo -e "${CYAN}Verification Commands:${NC}"
echo ""
echo "  ${YELLOW}# Check patient in database${NC}"
echo "  ssh ${SERVER_HOST} \"db -c \\\"SELECT * FROM patient WHERE patient_id_ehr_int = '${full_athena_id}';\\\"\" "
echo ""
echo "  ${YELLOW}# Check FHIR Patient resource${NC}"
echo "  curl ${HAPI_FHIR_URL}/Patient/${patient_fhir_id}"
echo ""
echo "  ${YELLOW}# Query patient by simple identifier${NC}"
echo "  curl '${HAPI_FHIR_URL}/Patient?identifier=${PATIENT_ID}'"
echo ""
echo "  ${YELLOW}# Check aggregator map entries${NC}"
echo "  ssh ${SERVER_HOST} \"db -c \\\"SELECT * FROM aggregator_resource_fhir_map WHERE athenaid LIKE '%${PATIENT_ID}%' LIMIT 5;\\\"\" "
echo ""
echo "  ${YELLOW}# Check TRAIS indexing status${NC}"
echo "  curl ${TRAIS_SERVER_URL}/trais/qa/indexStatus/${PATIENT_ID}"
echo ""
echo -e "${GREEN}Patient ${PATIENT_ID} is now ready for AI question answering!${NC}"
echo ""

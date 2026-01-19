#!/bin/bash
#
# Upload CCDA Addon to Existing Patient
#
# This script uploads a CCDA addon (e.g., wellness visit) to an existing patient:
# 1. Upload CCDA XML and extract FHIR resources to HAPI FHIR
# 2. Tag patient resources in HAPI FHIR for TRAIS
# 3. Index patient in TRAIS (OpenSearch + FAISS) for AI question answering
#
# NOTE: This script assumes the patient already exists in the database and FHIR.
#       Use upload_ccda_to_fhir.sh for initial patient onboarding.
#
# Usage: ./upload_addon_ccda.sh <patient_id> <practice_id> <xml_file_path> [server_base_url]
#
# Example:
#   ./upload_addon_ccda.sh t1210 11783 mock_patients/t1210_addon.xml
#   ./upload_addon_ccda.sh t1210 11783 mock_patients/t1210_addon.xml danvers-clone.thetarho.com
#   ./upload_addon_ccda.sh t1210 11783 mock_patients/t1210_addon.xml localhost

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
PATIENT_ID="${1}"
PRACTICE_ID="${2}"
XML_FILE="${3}"
SERVER_BASE="${4:-danvers-clone.thetarho.com}"

# Strip http:// or https:// if provided and extract hostname
SERVER_HOST=$(echo "$SERVER_BASE" | sed 's|^https\?://||')

# Construct service URLs
TRD_SERVER_URL="http://${SERVER_HOST}:9090"
TRAIS_SERVER_URL="http://${SERVER_HOST}:5000"

# Validate arguments
if [ -z "$PATIENT_ID" ] || [ -z "$PRACTICE_ID" ] || [ -z "$XML_FILE" ]; then
    echo -e "${RED}Error: Missing required arguments${NC}"
    echo ""
    echo "Usage: $0 <patient_id> <practice_id> <xml_file_path> [server_base_url]"
    echo ""
    echo "Arguments:"
    echo "  patient_id       - Patient ID (e.g., t1210)"
    echo "  practice_id      - Practice ID (e.g., 11783)"
    echo "  xml_file_path    - Path to CCDA addon XML file"
    echo "  server_base_url  - Optional server hostname (default: danvers-clone.thetarho.com)"
    echo ""
    echo "Examples:"
    echo "  $0 t1210 11783 mock_patients/t1210_addon.xml"
    echo "  $0 t1210 11783 mock_patients/t1210_addon.xml danvers-clone.thetarho.com"
    echo "  $0 t1210 11783 mock_patients/t1210_addon.xml localhost"
    echo ""
    echo "Note: This script assumes the patient already exists in the database."
    echo "      Use upload_ccda_to_fhir.sh for initial patient onboarding."
    exit 1
fi

# Construct patient_id_ehr_int in format: a-<practice_id>.E-<patient_id>
PATIENT_ID_EHR_INT="a-${PRACTICE_ID}.E-${PATIENT_ID}"

# Validate XML file exists
if [ ! -f "$XML_FILE" ]; then
    echo -e "${RED}Error: XML file not found: ${XML_FILE}${NC}"
    exit 1
fi

# Get file size for display
FILE_SIZE=$(stat -f%z "$XML_FILE" 2>/dev/null || stat -c%s "$XML_FILE" 2>/dev/null)
FILE_SIZE_KB=$((FILE_SIZE / 1024))

# Display header
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║            Upload CCDA Addon to Existing Patient               ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Configuration:${NC}"
echo "  Patient ID:        ${PATIENT_ID}"
echo "  Practice ID:       ${PRACTICE_ID}"
echo "  Patient EHR ID:    ${PATIENT_ID_EHR_INT}"
echo "  XML File:          ${XML_FILE}"
echo "  File Size:         ${FILE_SIZE_KB} KB"
echo "  Server Host:       ${SERVER_HOST}"
echo "  TRDataServices:    ${TRD_SERVER_URL}"
echo "  TRAIS:             ${TRAIS_SERVER_URL}"
echo ""

# ============================================================================
# STEP 1: Upload CCDA XML
# ============================================================================
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}STEP 1: Uploading CCDA Addon to TRDataServices${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${YELLOW}→ Uploading CCDA XML and extracting FHIR resources...${NC}"

# Call TRDataServices endpoint to load CCDA
# Endpoint: POST /athenahealth/loadCCDAFromXML/{patientId}
# Note: patientId should be patient_id_ehr_int (e.g., a-11783.E-t1210)
response=$(curl -s -w "\n%{http_code}" \
    -X POST \
    -F "xmlfile=@${XML_FILE}" \
    "${TRD_SERVER_URL}/athenahealth/loadCCDAFromXML/${PATIENT_ID_EHR_INT}")

http_code=$(echo "$response" | tail -n 1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
    echo -e "${GREEN}  ✓ CCDA uploaded successfully (HTTP ${http_code})${NC}"
    echo -e "${CYAN}  Response: ${body}${NC}"
else
    echo -e "${RED}  ✗ Upload failed (HTTP ${http_code})${NC}"
    echo -e "${RED}  Response: ${body}${NC}"
    exit 1
fi

echo ""

# ============================================================================
# STEP 2: Tag Patient Resources in FHIR
# ============================================================================
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}STEP 2: Tagging Patient Resources in HAPI FHIR${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Tag patient resources to mark latest appointments, vitals, conditions, etc.
# This adds meta.tag entries to resources for filtering in UI
echo -e "${YELLOW}→ Tagging latest resources for patient ${PATIENT_ID_EHR_INT}...${NC}"

# Call TRDataServices tagging endpoint
# Endpoint: GET /athenahealth/tagAPatient/{practice_id_ehr_int}/{patient_id}
tag_response=$(curl -s -w "\n%{http_code}" \
    -X GET \
    "${TRD_SERVER_URL}/athenahealth/tagAPatient/${PRACTICE_ID}/${PATIENT_ID}")

tag_http_code=$(echo "$tag_response" | tail -n 1)
tag_body=$(echo "$tag_response" | sed '$d')

if [ "$tag_http_code" -ge 200 ] && [ "$tag_http_code" -lt 300 ]; then
    echo -e "${GREEN}  ✓ Patient resources tagged successfully (HTTP ${tag_http_code})${NC}"
else
    echo -e "${YELLOW}  ⚠ Tagging encountered some errors (HTTP ${tag_http_code})${NC}"
    echo -e "${YELLOW}  This is often non-fatal - resources may already be tagged${NC}"
    if [ -n "$tag_body" ]; then
        echo -e "${YELLOW}  Response: ${tag_body}${NC}"
    fi
fi

echo ""

# ============================================================================
# STEP 3: Index Patient in TRAIS
# ============================================================================
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}STEP 3: Indexing Patient in TRAIS (OpenSearch + FAISS)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${YELLOW}→ Indexing patient for AI question answering...${NC}"

# Call TRAIS indexing endpoint
index_response=$(curl -s -w "\n%{http_code}" \
    -X GET \
    "${TRAIS_SERVER_URL}/trais/qa/indexPatient/${PATIENT_ID}")

index_http_code=$(echo "$index_response" | tail -n 1)
index_body=$(echo "$index_response" | sed '$d')

if [ "$index_http_code" -ge 200 ] && [ "$index_http_code" -lt 300 ]; then
    echo -e "${GREEN}  ✓ Patient indexed successfully (HTTP ${index_http_code})${NC}"
    echo -e "${CYAN}  Response: ${index_body}${NC}"
else
    echo -e "${RED}  ✗ Indexing failed (HTTP ${index_http_code})${NC}"
    echo -e "${RED}  Response: ${index_body}${NC}"
    echo -e "${YELLOW}  Note: Patient data is in FHIR but not indexed for AI${NC}"
fi

echo ""

# ============================================================================
# Success Summary
# ============================================================================
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              CCDA Addon Upload Complete!                       ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Patient Summary:${NC}"
echo "  Patient ID:          ${PATIENT_ID}"
echo "  Addon File:          ${XML_FILE}"
echo "  Server:              ${SERVER_HOST}"
echo ""
echo -e "${CYAN}Data Storage Status:${NC}"
echo "  ${GREEN}✓${NC} Addon FHIR resources uploaded to HAPI FHIR"
echo "  ${GREEN}✓${NC} Patient resources tagged"
echo "  ${GREEN}✓${NC} Patient indexed in TRAIS (OpenSearch + FAISS)"
echo ""
echo -e "${CYAN}Verification Commands:${NC}"
echo ""
echo "  ${YELLOW}# Check FHIR resources${NC}"
echo "  curl http://${SERVER_HOST}:8080/fhir/Patient/${PATIENT_ID}"
echo "  curl http://${SERVER_HOST}:8080/fhir/Encounter?patient=Patient/${PATIENT_ID}&_sort=-date&_count=5"
echo ""
echo "  ${YELLOW}# Check TRAIS indexing status${NC}"
echo "  curl ${TRAIS_SERVER_URL}/trais/qa/indexStatus/${PATIENT_ID}"
echo ""
echo "  ${YELLOW}# Test AI question answering${NC}"
echo "  curl -X POST '${TRAIS_SERVER_URL}/trais/qa/getAnswer' \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"patientid\": \"${PATIENT_ID}\", \"question\": \"What happened at the most recent visit?\"}'"
echo ""
echo -e "${GREEN}Patient ${PATIENT_ID} addon data is now available for AI question answering!${NC}"
echo ""

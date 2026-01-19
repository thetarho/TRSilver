./run_synthea -p 1 -g M -a 38-70
python3 ./scripts/convert_to_athena_format.py --input output/fhir/Bennie663_Kautzer186_2d719f2f-bcd3-d2b0-fc2e-80a8d8cf9b47.json --output t1210_bundle.json --patient-id 1210 --practice-id a-1959493
python3 scripts/split_bundle_by_resource.py --input mock_patients/bundles/t1210_bundle.json --output mock_patients/t1210
./scripts/upload_fhir_bundles_to_hapi.sh t1210 --server qa-provider-1.thetarho.com --practice-id 1959493

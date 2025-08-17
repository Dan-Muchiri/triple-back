from models import TestType
from models import Medicine
import csv
import json

test_types = [
    # Lab Tests
    TestType(name="Blood Group", price=200.0, category="lab"),
    TestType(name="Full Hemograms (FHG)", price=700.0, category="lab"),
    TestType(name="HBA1C", price=1000.0, category="lab"),
    TestType(name="Prostate Specific Antigen", price=1400.0, category="lab"),
    TestType(name="Kidney Function Tests", price=1500.0, category="lab"),
    TestType(name="Liver Function Test (LFTs)", price=2400.0, category="lab"),
    TestType(name="Malaria (MRDT)", price=250.0, category="lab"),
    TestType(name="Stool for O/C", price=250.0, category="lab"),
    TestType(name="H Pylori Antigen", price=700.0, category="lab"),
    TestType(name="H Pylori Antibody", price=700.0, category="lab"),
    TestType(name="Urinalysis", price=200.0, category="lab"),
    TestType(name="VDRL", price=250.0, category="lab"),
    TestType(name="Pregnancy Test (PDT)", price=100.0, category="lab"),
    TestType(name="Rheumatoid Factor (RF)", price=400.0, category="lab"),
    TestType(name="Salmonella Antigen", price=500.0, category="lab"),
    TestType(name="Lipid Profile", price=500.0, category="lab"),
    TestType(name="Urea", price=300.0, category="lab"),
    TestType(name="Calcium", price=400.0, category="lab"),
    TestType(name="Sodium", price=300.0, category="lab"),
    TestType(name="Potassium", price=300.0, category="lab"),
    TestType(name="Cholesterol", price=300.0, category="lab"),
    TestType(name="TSH", price=1300.0, category="lab"),
    TestType(name="T4, T3", price=1500.0, category="lab"),
    TestType(name="Creatinine", price=300.0, category="lab"),
    TestType(name="Albumin (ALB)", price=300.0, category="lab"),
    TestType(name="Total Protein (TP)", price=1000.0, category="lab"),
    TestType(name="Bilirubin (Total & Direct)", price=600.0, category="lab"),
    TestType(name="Electrolytes (NA, K, CL, CA)", price=1200.0, category="lab"),
    TestType(name="ALT (GTP)", price=300.0, category="lab"),
    TestType(name="AST (GOT)", price=300.0, category="lab"),
    TestType(name="HB", price=150.0, category="lab"),
    TestType(name="ESR", price=200.0, category="lab"),
    TestType(name="Blood Sugar", price=150.0, category="lab"),
    TestType(name="HIV", price=150.0, category="lab"),
    TestType(name="BS for MPS", price=200.0, category="lab"),

    # Imaging Tests
        TestType(name="Shoulder X-Ray", price=1000.0, category="imaging"),
        TestType(name="Humerus X-Ray", price=1000.0, category="imaging"),
        TestType(name="Elbow X-Ray", price=550.0, category="imaging"),
        TestType(name="Radioulnar X-Ray", price=550.0, category="imaging"),
        TestType(name="Wrist X-Ray", price=550.0, category="imaging"),
        TestType(name="Hand X-Ray", price=550.0, category="imaging"),
        TestType(name="Clavicle X-Ray", price=700.0, category="imaging"),
        TestType(name="Chest X-Ray", price=800.0, category="imaging"),
        TestType(name="Abdomen X-Ray", price=700.0, category="imaging"),
        TestType(name="Pelvic X-Ray", price=1000.0, category="imaging"),
        TestType(name="Femur X-Ray", price=1000.0, category="imaging"),
        TestType(name="Knee X-Ray", price=700.0, category="imaging"),
        TestType(name="Tibia Fibula X-Ray", price=700.0, category="imaging"),
        TestType(name="Ankle X-Ray", price=700.0, category="imaging"),
        TestType(name="Foot X-Ray", price=700.0, category="imaging"),
        TestType(name="Lumber Sacral X-Ray", price=1000.0, category="imaging"),
        TestType(name="Obstetric U/S", price=1900.0, category="imaging"),
        TestType(name="Abd/Pelvic U/S", price=1900.0, category="imaging"),
        TestType(name="Breast U/S", price=1500.0, category="imaging"),
        TestType(name="Thyroid U/S", price=1900.0, category="imaging"),
        TestType(name="Local U/S", price=1900.0, category="imaging"),
        TestType(name="Testicular U/S", price=1900.0, category="imaging"),
        TestType(name="Prostate U/S", price=1900.0, category="imaging"),
        TestType(name="Doppler U/S", price=3000.0, category="imaging"),
]


# The `file_path` is updated to point to a CSV file in the 'backend' folder.
# The `csv` module can't read .xlsx files directly, so the filename needs to be a CSV.
file_path = "TRIPPLE TS  PHARMACY  DEPARTMENT.csv"


# Define the final list to store the Medicine instances.
medicines_data = []

# Open and read the CSV file.
try:
    with open(file_path, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)

        # Skip the initial rows that contain headers and blank space.
        for _ in range(3):
            next(reader)

        # Iterate over each row in the CSV file after the headers.
        for row in reader:
            # Check if the row has enough columns to be valid data and a drug name.
            if len(row) >= 7 and row[1]:
                # Extract data, handling potential errors and cleaning up strings.
                name = row[1].strip()
                unit = row[2].strip()
                
                # Use try-except blocks to safely convert string data to numbers.
                try:
                    stock = int(float(row[3].strip()))
                except (ValueError, IndexError):
                    stock = 0

                try:
                    buying_price = float(row[4].strip())
                except (ValueError, IndexError):
                    buying_price = 0.0
                
                try:
                    selling_price = float(row[5].strip())
                except (ValueError, IndexError):
                    selling_price = 0.0

                try:
                    sold_units = int(float(row[6].strip()))
                except (ValueError, IndexError):
                    sold_units = 0

                # Create a Medicine instance directly.
                # Create a Medicine instance directly with keyword args.
                medicine = Medicine(
                    name=name,
                    unit=unit,
                    stock=stock,
                    sold_units=sold_units,        # ✅ use the 6th column
                    buying_price=buying_price,
                    selling_price=selling_price
                )
                
                # Add the new instance to our list.
                medicines_data.append(medicine)


except FileNotFoundError:
    print(f"Error: The file '{file_path}' was not found.")
except Exception as e:
    print(f"An error occurred: {e}")
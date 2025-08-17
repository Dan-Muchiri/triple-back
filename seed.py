from random import choice, randint, uniform
from faker import Faker
from datetime import datetime
from flask_bcrypt import Bcrypt
import phonenumbers

# Local imports
from app import app  # Flask app instance
from models import db, User, Patient, TriageRecord, Visit, roles, genders, Consultation, TestRequest, Prescription, Payment, payment_methods, TestType, Medicine
from prices import test_types, medicines_data 


bcrypt = Bcrypt()
fake = Faker()

visit_stages = (
    'reception',
    'waiting_triage',
    'waiting_consultation',
    'waiting_lab',
    'waiting_imaging',
    'waiting_pharmacy',
    'complete'
)



def create_user(role):
    """Creates a fake user with the given role."""
    first_name = fake.first_name()
    last_name = fake.last_name()
    email = f"{first_name.lower()}.{last_name.lower()}@clinic.com"
    password = 'password123'
    national_id = str(randint(10000000, 99999999))
    # Kenyan phone
    local_number = f"07{randint(10_000_000, 99_999_999)}"
    parsed_phone = phonenumbers.parse(local_number, "KE")
    formatted_phone = phonenumbers.format_number(parsed_phone, phonenumbers.PhoneNumberFormat.E164)

    user = User(
        first_name=first_name,
        last_name=last_name,
        email=email,
        role=role,
        phone_number=formatted_phone,
        national_id=national_id
    )
    user.password = password  # triggers the @password.setter
    return user

def create_patient():
    first_name = fake.first_name()
    last_name = fake.last_name()
    gender = choice(genders)
    dob = fake.date_of_birth(minimum_age=1, maximum_age=90)
    email = f"{first_name.lower()}.{last_name.lower()}@gmail.com"
    national_id = str(randint(10000000, 99999999))

    # Kenyan phone
    local_number = f"07{randint(10_000_000, 99_999_999)}"
    parsed_phone = phonenumbers.parse(local_number, "KE")
    formatted_phone = phonenumbers.format_number(parsed_phone, phonenumbers.PhoneNumberFormat.E164)

    return Patient(
        first_name=first_name,
        last_name=last_name,
        gender=gender,
        dob=dob,
        phone_number=formatted_phone,
        email=email,
        national_id=national_id
    )

def create_visit(patient_id):
    return Visit(
        patient_id=patient_id,
        stage=choice(visit_stages)
    )



def create_triage_record(patient_id, nurse_id):
    """Creates a fake triage record for a patient and nurse."""
    return TriageRecord(
        patient_id=patient_id,
        nurse_id=nurse_id,
        temperature=round(uniform(35.5, 39.5), 1),
        weight=round(uniform(40, 120), 1),
        height=round(uniform(140, 200), 1),
        blood_pressure=f"{randint(90, 140)}/{randint(60, 90)}",
        pulse_rate=randint(60, 110),
        notes=fake.sentence()
    )

def create_consultation(patient_id, doctor_id):
    return Consultation(
        patient_id=patient_id,
        doctor_id=doctor_id,
        diagnosis=fake.sentence(nb_words=6),
        notes=fake.paragraph(nb_sentences=3),
        chief_complain=fake.sentence(nb_words=8),
        physical_exam=fake.paragraph(nb_sentences=2),
        systemic_exam=fake.paragraph(nb_sentences=2)
    )

def seed_test_types():
    db.session.add_all(test_types)
    db.session.commit()
    print(f"✅ Seeded {len(test_types)} test types.")



def create_test_request(consultation_id, category='lab', technician_id=None):
    status = choice(['pending', 'completed'])
    results = fake.sentence(nb_words=8) if status == 'completed' else None

    # Pick a TestType from DB by category
    test_type = TestType.query.filter_by(category=category).order_by(db.func.random()).first()

    return TestRequest(
        consultation_id=consultation_id,
        technician_id=technician_id,
        test_type=test_type,  # ✅ correct, assign object not string
        results=results,
        notes=fake.sentence(nb_words=10),
        status=status
    )

def seed_medicines():
    if not medicines_data:
        print("❌ No medicines parsed from CSV, skipping seeding...")
        return

    db.session.add_all(medicines_data)
    db.session.commit()
    print(f"✅ Seeded {len(medicines_data)} medicines.")





def create_prescription(consultation_id, pharmacist_id=None):
    status = choice(['pending', 'dispensed'])  # Mix of pending and done

    # ✅ Pick a real medicine from DB
    medicine = Medicine.query.order_by(db.func.random()).first()

    if not medicine:
        raise Exception("❌ No medicines found in DB to seed prescriptions!")

    return Prescription(
        consultation_id=consultation_id,
        pharmacist_id=pharmacist_id,
        medicine_id=medicine.id,  # ✅ use id, not string
        dosage=choice(['1 tab twice daily', '2 tabs once daily', '1 tab after meals']),
        instructions=fake.sentence(nb_words=10),
        status=status,
        dispensed_units=0
    )



def create_payment(visit_id, receptionist_id):
    return Payment(
        visit_id=visit_id,
        amount=round(uniform(500, 3000), 2),
        service_type=choice(['Test', 'Prescription']),
        payment_method=choice(payment_methods),
        mpesa_receipt=fake.uuid4()[:10].upper(),
        receptionist_id=receptionist_id
    )



if __name__ == '__main__':
    with app.app_context():
        print("🔄 Dropping and recreating tables...")
        db.drop_all()
        db.create_all()

        print("🌱 Seeding users...")

        dan = User(
            first_name= 'Dan',
            last_name= 'Munene',
            email= 'danspmunene@gmail.com',
            role="admin",
            password = "admin",
        )

        db.session.add(dan)
        db.session.commit()
    
        # users = [create_user(role) for role in roles]
        # db.session.add_all(users)
        # db.session.commit()

        # print(f"✅ Seeded {len(users)+1} users.")

        # print("🌱 Seeding patients...")
        # patients = [create_patient() for _ in range(10)]
        # db.session.add_all(patients)
        # db.session.commit()

        # print(f"✅ Seeded {len(patients)} patients.")

        # print("🌱 Seeding visits...")
        # visits = []

        # for patient in patients:
        #     # 1. Completed visit
        #     complete_visit = Visit(
        #         patient_id=patient.id,
        #         stage='complete'
        #     )
        #     visits.append(complete_visit)

        #     # 2. Random incomplete visit
        #     incomplete_stage = choice([s for s in visit_stages if s != 'complete'])
        #     incomplete_visit = Visit(
        #         patient_id=patient.id,
        #         stage=incomplete_stage
        #     )
        #     visits.append(incomplete_visit)

        # db.session.add_all(visits)
        # db.session.commit()

        # print(f"✅ Seeded {len(visits)} visits.")


        # print("🌱 Seeding triage records...")

        # nurses = User.query.filter_by(role='nurse').all()
        # if not nurses:
        #     raise Exception("❌ No nurses found in users!")

        # triage_records = []

        # for visit in visits:
        #         nurse = choice(nurses)
        #         triage = create_triage_record(patient_id=visit.patient_id, nurse_id=nurse.id)

        #         db.session.add(triage)
        #         db.session.flush()  # So we get triage.id before visit update

        #         visit.triage_id = triage.id

        #         triage_records.append(triage)

        # db.session.commit()

        # print(f"✅ Seeded {len(triage_records)} triage records and linked them to visits.")

        # print("🌱 Seeding consultations...")

        # doctors = User.query.filter_by(role='doctor').all()
        # if not doctors:
        #     raise Exception("❌ No doctors found in users!")

        # consultations = []
        # for visit in visits:
        #     doctor = choice(doctors)
        #     consultation = create_consultation(patient_id=visit.patient_id, doctor_id=doctor.id)
            
        #     db.session.add(consultation)
        #     db.session.flush()

        #     visit.consultation_id = consultation.id

        #     consultations.append(consultation)

        # db.session.commit()

        # print(f"✅ Seeded {len(consultations)} consultations.")

        # ✅ Seed test types before requests
        print("🌱 Seeding test types...")
        seed_test_types()

        print("🌱 Seeding medicines...")
        seed_medicines()



        # print("🌱 Seeding test requests...")

        # lab_techs = User.query.filter_by(role='lab_tech').all()
        # imaging_techs = User.query.filter_by(role='imaging_tech').all()

        # if not lab_techs:
        #     raise Exception("❌ No lab technicians found!")
        # if not imaging_techs:
        #     raise Exception("❌ No imaging technicians found!")

        # test_requests = []

        # for consultation in consultations:
        #     # Always create at least one lab test
        #     lab_tech = choice(lab_techs)
        #     test_requests.append(
        #         create_test_request(
        #             consultation_id=consultation.id,
        #             category='lab',
        #             technician_id=lab_tech.id
        #         )
        #     )

        #     # Always create at least one imaging test
        #     imaging_tech = choice(imaging_techs)
        #     test_requests.append(
        #         create_test_request(
        #             consultation_id=consultation.id,
        #             category='imaging',
        #             technician_id=imaging_tech.id
        #         )
        #     )

        #     # Optionally add 0–2 extra random test requests
        #     for _ in range(randint(0, 2)):
        #         category = choice(['lab', 'imaging'])
        #         tech = choice(lab_techs) if category == 'lab' else choice(imaging_techs)
        #         test_requests.append(
        #             create_test_request(
        #                 consultation_id=consultation.id,
        #                 category=category,
        #                 technician_id=tech.id
        #             )
        #         )

        # db.session.add_all(test_requests)
        # db.session.commit()

        # print(f"✅ Seeded {len(test_requests)} test requests.")


        # print("🌱 Seeding prescriptions...")

        # pharmacists = User.query.filter_by(role='pharmacist').all()
        # if not pharmacists:
        #     raise Exception("❌ No pharmacists found!")

        # prescriptions = []
        # for consultation in consultations:
        #     for _ in range(randint(1, 2)):
        #         pharmacist = choice(pharmacists) if randint(0, 1) else None
        #         prescription = create_prescription(
        #             consultation_id=consultation.id,
        #             pharmacist_id=pharmacist.id if pharmacist else None
        #         )
        #         prescriptions.append(prescription)

        # db.session.add_all(prescriptions)
        # db.session.commit()

        # print(f"✅ Seeded {len(prescriptions)} prescriptions.")

        # print("🌱 Seeding payments and linking to test requests or prescriptions...")

        # receptionists = User.query.filter_by(role='receptionist').all()
        # if not receptionists:
        #     raise Exception("❌ No receptionists found!")

        # payments = []

        # # ✅ Some test requests with payments, some without
        # for test in test_requests:
        #     if choice([True, False]):
        #         visit = Visit.query.filter_by(consultation_id=test.consultation_id).first()
        #         if visit:
        #             receptionist = choice(receptionists)
        #             payment = create_payment(visit.id, receptionist.id)
        #             payment.test_request_id = test.id  # ✅ Correct way to link
        #             db.session.add(payment)
        #             payments.append(payment)


        # # ✅ Some prescriptions with payments, some without
        # for pres in prescriptions:
        #     if choice([True, False]):
        #         visit = Visit.query.filter_by(consultation_id=pres.consultation_id).first()
        #         if visit:
        #             receptionist = choice(receptionists)
        #             payment = create_payment(visit.id, receptionist.id)
        #             payment.prescription_id = pres.id  # ✅ Correct way
        #             db.session.add(payment)
        #             payments.append(payment)


        # db.session.commit()

        # print(f"✅ Seeded {len(payments)} payments and linked them to test requests or prescriptions.")







        

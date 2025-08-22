from sqlalchemy_serializer import SerializerMixin
from sqlalchemy.orm import validates
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, Enum
from sqlalchemy.ext.hybrid import hybrid_property
from flask_bcrypt import Bcrypt
from datetime import datetime
import pytz
import re
import phonenumbers

# Define metadata, instantiate db
metadata = MetaData(naming_convention={
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
})
db = SQLAlchemy(metadata=metadata)
bcrypt = Bcrypt()

roles = (
    'receptionist',
    'nurse',
    'doctor',
    'lab_tech',       # for 'lab' category test requests
    'imaging_tech',   # for 'imaging' category test requests
    'pharmacist',
    'admin'
)
genders = ('male', 'female')
visit_stages = ('reception','waiting_triage', 'waiting_consultation','waiting_lab','waiting_imaging','waiting_pharmacy','complete')
otc_stages = ('reception','waiting_pharmacy','complete')
lab_statuses = ('pending', 'completed')

payment_methods = ('cash', 'mpesa')
nairobi_tz = pytz.timezone('Africa/Nairobi')

class User(db.Model, SerializerMixin):
    __tablename__ = 'users'

    def to_dict(self):
        return {
            'id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'national_id': self.national_id,
            'phone_number': self.phone_number,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    national_id = db.Column(db.String(20), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    _password_hash = db.Column(db.String, nullable=False)
    role = db.Column(Enum(*roles, name='user_roles'), nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(nairobi_tz)
    )

    def __repr__(self):
        return f'<User {self.first_name} {self.last_name} | Email: {self.email}>'

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.role})'
    
    # Define relationship
    triage_records = db.relationship('TriageRecord', back_populates='nurse', cascade='all, delete-orphan')
    consultations = db.relationship('Consultation', back_populates='doctor', cascade='all, delete-orphan')
    test_requests = db.relationship('TestRequest', back_populates='technician', cascade='all, delete-orphan')
    prescriptions = db.relationship('Prescription', back_populates='pharmacist', cascade='all, delete-orphan')



    @validates('first_name')
    def validate_first_name(self, key, first_name):
        if not first_name:
            raise ValueError('First name is required')
        if len(first_name) > 50:
            raise ValueError('First name must be less than 50 characters')
        return first_name

    @validates('last_name')
    def validate_last_name(self, key, last_name):
        if not last_name:
            raise ValueError('Last name is required')
        if len(last_name) > 50:
            raise ValueError('Last name must be less than 50 characters')
        return last_name

    @validates('email')
    def validate_email(self, key, email):
        if not email:
            raise ValueError('Email is required')
        email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        if not re.match(email_pattern, email):
            raise ValueError('Invalid email format')
        return email
    
    @validates('national_id')
    def validate_national_id(self, key, national_id):
        if national_id:
            if not re.match(r'^\d{6,12}$', national_id):
                raise ValueError("National ID must be 6–12 digits")
        return national_id

    @validates('phone_number')
    def validate_phone_number(self, key, phone_number):
        if phone_number:
            try:
                parsed_number = phonenumbers.parse(phone_number, "KE")
                if not phonenumbers.is_valid_number(parsed_number):
                    raise ValueError('Invalid Kenyan phone number')
            except phonenumbers.phonenumberutil.NumberParseException:
                raise ValueError('Invalid phone number format. Use "0712345678" or "+254712345678"')
            return phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
        return None

    @hybrid_property
    def password(self):
        return self._password_hash

    @password.setter
    def password(self, plaintext_password):
        self._password_hash = bcrypt.generate_password_hash(plaintext_password).decode('utf-8')

    def check_password(self, plaintext_password):
        return bcrypt.check_password_hash(self._password_hash, plaintext_password)



class Patient(db.Model, SerializerMixin):
    __tablename__ = 'patients'

    def to_dict(self):
        return {
            'id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'gender': self.gender,
            'dob': self.dob.isoformat() if self.dob else None,
            'age': self.age,
            'national_id': self.national_id,
            'phone_number': self.phone_number,
            'email': self.email,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'visits': [
                {
                    'id': v.id,
                    'triage_id': v.triage_id,
                    'consultation_id': v.consultation_id,
                    'stage': v.stage,
                    'consultation': v.consultation.to_dict() if v.consultation else None,
                    'test_requests': [tr.to_dict() for tr in v.consultation.test_requests] if v.consultation else [],
                    'prescriptions': [p.to_dict() for p in v.consultation.prescriptions] if v.consultation else [],
                    'created_at': v.created_at.isoformat() if v.created_at else None
                }
                for v in self.visits
            ]
        }

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    gender = db.Column(Enum(*genders, name='gender_enum'), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    national_id = db.Column(db.String(20), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(nairobi_tz))

    @property
    def age(self):
        today = datetime.now(nairobi_tz).date()
        return today.year - self.dob.year - ((today.month, today.day) < (self.dob.month, self.dob.day))


    def __repr__(self):
        return f"<Patient {self.first_name} {self.last_name}>"
    
    # Define relationship
    triage_records = db.relationship('TriageRecord', back_populates='patient', cascade='all, delete-orphan')
    visits = db.relationship('Visit', back_populates='patient', cascade='all, delete-orphan')
    consultations = db.relationship('Consultation', back_populates='patient', cascade='all, delete-orphan')


    @validates('first_name', 'last_name')
    def validate_name(self, key, name):
        if not name or len(name) > 50:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} must be present and under 50 characters.")
        return name

    @validates('email')
    def validate_email(self, key, email):
        if email:
            email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
            if not re.match(email_pattern, email):
                raise ValueError('Invalid email format')
        return email
    
    @validates('dob')
    def validate_dob(self, key, dob):
        if not dob:
            raise ValueError("Date of birth is required.")
        
        today = datetime.now(nairobi_tz).date()
        if dob >= today:
            raise ValueError("Date of birth must be in the past.")

        if dob < datetime(1900, 1, 1).date():
            raise ValueError("Date of birth is too far in the past.")
        
        return dob

    
    @validates('national_id')
    def validate_national_id(self, key, national_id):
        if national_id:
            if not re.match(r'^\d{6,12}$', national_id):
                raise ValueError("National ID must be 6–12 digits")
        return national_id

    @validates('phone_number')
    def validate_phone_number(self, key, phone_number):
        if phone_number:
            try:
                parsed_number = phonenumbers.parse(phone_number, "KE")
                if not phonenumbers.is_valid_number(parsed_number):
                    raise ValueError('Invalid Kenyan phone number')
            except phonenumbers.phonenumberutil.NumberParseException:
                raise ValueError('Invalid phone number format. Use "0712345678" or "+254712345678"')
            return phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
        return None

    
class Visit(db.Model, SerializerMixin):
    __tablename__ = 'visits'

    id = db.Column(db.Integer, primary_key=True)

    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    triage_id = db.Column(db.Integer, db.ForeignKey('triage_records.id'), nullable=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultations.id'), nullable=True)

    stage = db.Column(Enum(*visit_stages, name='visit_stage_enum'), default='reception', nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(nairobi_tz))

    # Relationships
    patient = db.relationship('Patient', back_populates='visits')
    triage = db.relationship('TriageRecord', back_populates='visit', uselist=False)
    consultation = db.relationship('Consultation', back_populates='visit', uselist=False)
    test_requests = db.relationship('TestRequest', back_populates='visit', cascade='all, delete-orphan')  # 👈 new


    def __repr__(self):
        return f"<Visit PatientID={self.patient_id}, Stage={self.stage}>"
    
   
    @property
    def total_charges(self):
        consultation_total = self.consultation.fee if self.consultation else 0

        # 👇 Add both direct & consultation-based test requests
        test_total = sum(tr.amount for tr in self.test_requests)  
        if self.consultation:
            test_total += sum(tr.amount for tr in self.consultation.test_requests)

        prescription_total = 0
        if self.consultation:
            prescription_total = sum(
                (p.dispensed_units or 0) * (p.medicine.selling_price if p.medicine else 0)
                for p in self.consultation.prescriptions
            )

        return consultation_total + test_total + prescription_total


    @property
    def total_payments(self):
        return sum(p.amount for p in self.payments)

    @property
    def balance(self):
        return self.total_charges - self.total_payments

    def to_dict(self):
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'stage': self.stage,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'patient': self.patient.to_dict() if self.patient else None,
            'triage': self.triage.to_dict() if self.triage else None,
            'consultation': self.consultation.to_dict() if self.consultation else None,
            'direct_test_requests': [tr.to_dict() for tr in self.test_requests],
            'test_requests': [tr.to_dict() for tr in self.consultation.test_requests] if self.consultation else [],
            'prescriptions': [p.to_dict() for p in self.consultation.prescriptions] if self.consultation else [],
            'payments': [p.to_dict() for p in self.payments],
            'total_charges': self.total_charges,
            'total_payments': self.total_payments,
            'balance': self.balance,
        }
    
class TriageRecord(db.Model, SerializerMixin):
    __tablename__ = 'triage_records'

    def to_dict(self):
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'nurse_id': self.nurse_id,
            'visit_id': self.visit.id if self.visit else None,
            'temperature': self.temperature,
            'weight': self.weight,
            'height': self.height,
            'bmi': self.bmi,
            'blood_pressure': self.blood_pressure,
            'pulse_rate': self.pulse_rate,
            'respiration_rate': self.respiration_rate,
            'spo2': self.spo2,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    id = db.Column(db.Integer, primary_key=True)

    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    nurse_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)


    temperature = db.Column(db.Float, nullable=False)
    weight = db.Column(db.Float, nullable=False)
    height = db.Column(db.Float, nullable=False)
    blood_pressure = db.Column(db.String(15), nullable=False)
    pulse_rate = db.Column(db.Integer, nullable=True)
    spo2 = db.Column(db.Integer, nullable=True)  # SpO₂ percentage
    respiration_rate = db.Column(db.Integer, nullable=True)  # breaths per minute
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(nairobi_tz))

    @property
    def bmi(self):
        height_m = self.height / 100  # convert cm to meters
        return round(self.weight / (height_m ** 2), 1) if height_m else None

    # Relationships
    patient = db.relationship('Patient', back_populates='triage_records')
    nurse = db.relationship('User', back_populates='triage_records')
    visit = db.relationship('Visit', back_populates='triage', uselist=False)

    # === VALIDATIONS ===

    @validates('nurse_id')
    def validate_nurse_id(self, key, nurse_id):
        nurse = db.session.query(User).get(nurse_id)
        if not nurse:
            raise ValueError("Nurse ID does not exist")
        if nurse.role != 'nurse':
            raise ValueError("User must have the role 'nurse'")
        return nurse_id

    @validates('temperature')
    def validate_temperature(self, key, value):
        if value is not None and value < 20.0:
            raise ValueError("Temperature must be realistic (≥ 20°C)")
        return value

    @validates('weight')
    def validate_weight(self, key, value):
        if value is not None and value <= 0:
            raise ValueError("Weight must be greater than 0")
        return value

    @validates('height')
    def validate_height(self, key, value):
        if value is not None and value <= 0:
            raise ValueError("Height must be greater than 0")
        return value

    @validates('blood_pressure')
    def validate_blood_pressure(self, key, value):
        pattern = r'^\d{1,3}/\d{1,3}$'
        if not re.match(pattern, value):
            raise ValueError("Blood pressure must be in format like '120/80'")
        return value

    @validates('pulse_rate')
    def validate_pulse_rate(self, key, value):
        if value is not None and value < 0:
            raise ValueError("Pulse rate must be non-negative")
        return value

    @validates('respiration_rate')
    def validate_respiration_rate(self, key, value):
        if value is not None and value < 0:
            raise ValueError("Respiration rate must be non-negative")
        return value

    @validates('spo2')
    def validate_spo2(self, key, value):
        if value is not None and value < 0:
            raise ValueError("SpO₂ must be non-negative")
        return value



class Consultation(db.Model, SerializerMixin):
    __tablename__ = 'consultations'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    diagnosis = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    chief_complain = db.Column(db.Text, nullable=True)
    physical_exam = db.Column(db.Text, nullable=True)
    systemic_exam = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(nairobi_tz))

    # 👇 new field
    fee = db.Column(db.Float, default=200, nullable=False)

    # Relationships
    patient = db.relationship('Patient', back_populates='consultations')
    doctor = db.relationship('User', back_populates='consultations')
    visit = db.relationship('Visit', back_populates='consultation', uselist=False)
    test_requests = db.relationship('TestRequest', back_populates='consultation', cascade='all, delete-orphan')
    prescriptions = db.relationship('Prescription', back_populates='consultation', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'doctor_id': self.doctor_id,
            'visit_id': self.visit.id if self.visit else None,
            'diagnosis': self.diagnosis,
            'notes': self.notes,
            'chief_complain': self.chief_complain,
            'physical_exam': self.physical_exam,
            'systemic_exam': self.systemic_exam,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'fee': self.fee,  # 👈 include consultation fee
            'test_requests': [tr.to_dict() for tr in self.test_requests],
            'prescriptions': [p.to_dict() for p in self.prescriptions]
        }




    def __repr__(self):
        return f"<Consultation PatientID={self.patient_id} DoctorID={self.doctor_id}>"

    # === VALIDATIONS ===

    @validates('doctor_id')
    def validate_doctor_id(self, key, doctor_id):
        doctor = db.session.get(User, doctor_id)
        if not doctor:
            raise ValueError("Doctor does not exist.")
        if doctor.role != 'doctor':
            raise ValueError("User must have the role 'doctor'.")
        return doctor_id

    @validates('patient_id')
    def validate_patient_id(self, key, patient_id):
        patient = db.session.get(Patient, patient_id)
        if not patient:
            raise ValueError("Patient does not exist.")
        return patient_id
    
class TestType(db.Model):
    __tablename__ = 'test_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(Enum('lab', 'imaging', name='test_category_enum'), nullable=False)  # ✅ moved here

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "price": self.price,
            "category": self.category
        }


    def __repr__(self):
        return f"<TestType {self.name} - {self.price} - {self.category}>"


    

class TestRequest(db.Model, SerializerMixin):
    __tablename__ = 'test_requests'

    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultations.id'), nullable=True)  # now nullable
    visit_id = db.Column(db.Integer, db.ForeignKey('visits.id'), nullable=True) 
    technician_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    test_type_id = db.Column(db.Integer, db.ForeignKey('test_types.id'), nullable=False)
    results = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(Enum('pending', 'completed', name='test_status_enum'), default='pending', nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(nairobi_tz))

    # Relationships
    consultation = db.relationship('Consultation', back_populates='test_requests')
    visit = db.relationship('Visit', back_populates='test_requests')
    technician = db.relationship('User', back_populates='test_requests')
    test_type = db.relationship('TestType')

    def to_dict(self):
        return {
            'id': self.id,
            'consultation_id': self.consultation_id,
            'visit_id': self.visit_id,
            'technician_id': self.technician_id,
            'test_type_id': self.test_type.id if self.test_type else None,
            'test_type': self.test_type.name if self.test_type else None,
            'category': self.test_type.category if self.test_type else None,  # ✅ derived
            'price': self.test_type.price if self.test_type else None,
            'results': self.results,
            'notes': self.notes,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


    @property
    def amount(self):
        return self.test_type.price if self.test_type else 0


    def __repr__(self):
        return f"<TestRequest Type='{self.test_type}' Category='{self.category}' Status='{self.status}'>"


    @validates('status')
    def validate_status(self, key, value):
        allowed = ('pending', 'completed')
        if value not in allowed:
            raise ValueError(f"Status must be one of {allowed}")
        return value

    @validates('category')
    def validate_category(self, key, value):
        if value not in ('lab', 'imaging'):
            raise ValueError("Category must be 'lab' or 'imaging'")
        return value

    @validates("technician_id")
    def validate_technician_id(self, key, technician_id):
        technician = User.query.get(technician_id)

        # ✅ use category from linked TestType
        if self.test_type and self.test_type.category == 'lab' and technician.role != 'lab_tech':
            raise ValueError("Lab tests must be assigned to a lab technician")
        if self.test_type and self.test_type.category == 'imaging' and technician.role != 'imaging_tech':
            raise ValueError("Imaging tests must be assigned to an imaging technician")

        return technician_id


class Medicine(db.Model):
    __tablename__ = 'medicines'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # remove unique=True
    stock = db.Column(db.Integer, default=0, nullable=False)
    sold_units = db.Column(db.Integer, default=0, nullable=False)  # ✅ new column
    buying_price = db.Column(db.Float, nullable=False)
    selling_price = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(50), nullable=False, default="tablet")  # ✅ Added field

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "stock": self.stock,
            "sold_units": self.sold_units,  # ✅ include in dict
            "buying_price": self.buying_price,
            "selling_price": self.selling_price,
            "unit": self.unit,
        }

    def __repr__(self):
        return f"<Medicine {self.name} - stock={self.stock} - sold={self.sold_units} - price={self.selling_price} - unit={self.unit}>"



class Prescription(db.Model, SerializerMixin):
    __tablename__ = 'prescriptions'

    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultations.id'), nullable=False)
    pharmacist_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)
    dosage = db.Column(db.String(50), nullable=False)
    instructions = db.Column(db.Text, nullable=True)

    status = db.Column(Enum('pending', 'dispensed', name='prescription_status_enum'),
                       default='pending', nullable=False)

    dispensed_units = db.Column(db.Integer, default=0, nullable=True)  

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(nairobi_tz))

    # Relationships
    consultation = db.relationship('Consultation', back_populates='prescriptions')
    pharmacist = db.relationship('User', back_populates='prescriptions')
    medicine = db.relationship('Medicine')

    def to_dict(self):
        price = None
        if self.medicine and self.dispensed_units:
            price = self.dispensed_units * self.medicine.selling_price

        return {
            'id': self.id,
            'consultation_id': self.consultation_id,
            'pharmacist_id': self.pharmacist_id,
            'medicine_id': self.medicine.id if self.medicine else None,
            'medication_name': self.medicine.name if self.medicine else None,
            'selling_price': self.medicine.selling_price if self.medicine else None,
            'dosage': self.dosage,
            'instructions': self.instructions,
            'status': self.status,
            'dispensed_units': self.dispensed_units,
            'price': price,  # ✅ new field
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }



    @validates('status')
    def validate_status(self, key, value):
        if value not in ('pending', 'dispensed'):
            raise ValueError(f"Invalid prescription status: {value}")
        return value
    
    @validates('pharmacist_id')
    def validate_pharmacist(self, key, pharmacist_id):
        if pharmacist_id is not None:
            pharmacist = db.session.get(User, pharmacist_id)
            if not pharmacist:
                raise ValueError("Pharmacist ID does not exist")
            if pharmacist.role != 'pharmacist':
                raise ValueError("User must have the role 'pharmacist'")
        return pharmacist_id

    
class Payment(db.Model, SerializerMixin):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)

    visit_id = db.Column(db.Integer, db.ForeignKey('visits.id'), nullable=True)
    otc_sale_id = db.Column(db.Integer, db.ForeignKey('otc_sales.id'), nullable=True)

    amount = db.Column(db.Float, nullable=False)
    service_type = db.Column(db.String(100), nullable=False)
    payment_method = db.Column(Enum(*payment_methods, name='payment_method_enum'), nullable=False)
    mpesa_receipt = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(nairobi_tz))

    receptionist_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # 🔗 Relationships
    visit = db.relationship('Visit', backref=db.backref('payments', cascade='all, delete-orphan'))
    otc_sale = db.relationship('OTCSale', backref=db.backref('payments', cascade='all, delete-orphan'))
    receptionist = db.relationship('User', backref='payments_recorded')

    def __repr__(self):
        return f"<Payment VisitID={self.visit_id} OTCSaleID={self.otc_sale_id} Amount={self.amount} Method={self.payment_method}>"

    def to_dict(self):
        return {
            'id': self.id,
            'visit_id': self.visit_id,
            'otc_sale_id': self.otc_sale_id,
            'amount': self.amount,
            'service_type': self.service_type,
            'payment_method': self.payment_method,
            'mpesa_receipt': self.mpesa_receipt,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'receptionist': self.receptionist.to_dict() if self.receptionist else None
        }

    # ✅ Validation
    @validates('receptionist_id')
    def validate_receptionist_id(self, key, receptionist_id):
        user = db.session.get(User, receptionist_id)
        if not user:
            raise ValueError("Receptionist not found")
        if user.role != 'receptionist':
            raise ValueError("User must have the role 'receptionist'")
        return receptionist_id

    @validates('amount')
    def validate_amount(self, key, value):
        if value <= 0:
            raise ValueError("Amount must be greater than 0")
        return value

    @validates('payment_method')
    def validate_payment_method(self, key, value):
        if value not in payment_methods:
            raise ValueError(f"Payment method must be one of {payment_methods}")
        return value

    
class OTCSale(db.Model, SerializerMixin):
    __tablename__ = 'otc_sales'

    id = db.Column(db.Integer, primary_key=True)
    patient_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(nairobi_tz))
    stage = db.Column(
        Enum(*otc_stages, name='otc_stage_enum'),
        default='waiting_pharmacy',
        nullable=False
    )

    # Relationships
    sales = db.relationship('PharmacySale', back_populates='otc_sale', cascade="all, delete-orphan")
    # 👇 payments relationship already linked from Payment

    @property
    def total_price(self):
        return sum(sale.total_price for sale in self.sales if sale.total_price)

    @property
    def total_payments(self):
        return sum(p.amount for p in self.payments)

    @property
    def balance(self):
        return self.total_price - self.total_payments

    def to_dict(self):
        return {
        'id': self.id,
        'patient_name': self.patient_name,
        'created_at': self.created_at.isoformat() if self.created_at else None,
        'sales': [sale.to_dict() for sale in self.sales],
        'total_charges': self.total_price,   # 🔥 unified naming
        'payments': [p.to_dict() for p in self.payments],
        'total_payments': self.total_payments,
        'balance': self.balance,
        'stage': self.stage,
    }



class PharmacySale(db.Model, SerializerMixin):
    __tablename__ = 'pharmacy_sales'

    id = db.Column(db.Integer, primary_key=True)
    otc_sale_id = db.Column(db.Integer, db.ForeignKey('otc_sales.id'), nullable=False)

    pharmacist_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)

    dispensed_units = db.Column(db.Integer, nullable=False, default=1)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(nairobi_tz))

    # Relationships
    otc_sale = db.relationship('OTCSale', back_populates='sales')
    pharmacist = db.relationship('User', backref='pharmacy_sales')
    medicine = db.relationship('Medicine')

    @property
    def total_price(self):
        return (self.medicine.selling_price * self.dispensed_units) if self.medicine else 0

    def to_dict(self):
        return {
            'id': self.id,
            'otc_sale_id': self.otc_sale_id,
            'pharmacist_id': self.pharmacist_id,
            'pharmacist': self.pharmacist.to_dict() if self.pharmacist else None,
            'medicine_id': self.medicine_id,
            'medication_name': self.medicine.name if self.medicine else None,
            'selling_price': self.medicine.selling_price if self.medicine else None,
            'dispensed_units': self.dispensed_units,
            'total_price': self.total_price,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
class PharmacyExpense(db.Model, SerializerMixin):
    __tablename__ = "pharmacy_expenses"

    id = db.Column(db.Integer, primary_key=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey("medicines.id"), nullable=False)
    quantity_added = db.Column(db.Integer, nullable=False)
    discount = db.Column(db.Float, default=0.0)  # discount 
    total_cost = db.Column(db.Float, nullable=False)  # automatically calculated
    created_at = db.Column(db.DateTime, default=datetime.now)

    # Relationships
    medicine = db.relationship("Medicine", backref="expenses")

    def __init__(self, medicine, quantity_added, discount=0.0):
        self.medicine = medicine
        self.quantity_added = quantity_added
        self.discount = discount
        self.total_cost = self.calculate_total()

    def calculate_total(self):
        if self.medicine and self.quantity_added:
            total = self.medicine.buying_price * self.quantity_added
            # Apply discount as a flat value
            if self.discount > 0:
                total -= self.discount
            return round(max(total, 0.0), 2)  # prevent negative totals
        return 0.0


    def to_dict(self):
        return {
            "id": self.id,
            "medicine_id": self.medicine_id,
            "medicine_name": self.medicine.name if self.medicine else None,
            "quantity_added": self.quantity_added,
            "buying_price": self.medicine.buying_price if self.medicine else None,
            "discount": self.discount,
            "total_cost": self.total_cost,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @validates("quantity_added")
    def validate_quantity(self, key, value):
        if value <= 0:
            raise ValueError("Quantity added must be greater than 0")
        return value

    @validates("discount")
    def validate_discount(self, key, value):
        if value < 0:
            raise ValueError("Discount must be positive")
        return value











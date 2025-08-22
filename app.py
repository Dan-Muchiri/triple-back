from flask import Flask, jsonify, request, make_response, session, Response, render_template_string
from flask_restful import Resource,Api
import os
from dotenv import load_dotenv
from flask_cors import CORS
from flask_migrate import Migrate
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import IntegrityError
from marshmallow import ValidationError
from models import db, User, roles, Patient, Visit, TriageRecord, Consultation, TestRequest, Prescription, Payment, TestType, Medicine, PharmacySale, OTCSale, PharmacyExpense
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from flask.views import MethodView
from sqlalchemy import func

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.json.compact = False

app.permanent_session_lifetime = timedelta(days=1)


migrate = Migrate(app, db)
db.init_app(app)


api = Api(app)

CORS(app)
    
# Set secret key
app.secret_key = os.environ.get('SECRET_KEY', 'fallback_secret')


@app.route('/receipt/<int:payment_id>', methods=['GET'])
def generate_receipt(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    visit = payment.visit
    patient = visit.patient

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(width / 2, height - 50, "TRIPLE T.S. MEDICLINIC")

    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(width / 2, height - 70, "OFFICIAL RECEIPT")

    # Info
    y = height - 120
    line_height = 20
    pdf.setFont("Helvetica", 11)

    info_lines = [
        f"Patient: {patient.first_name} {patient.last_name}",
        f"National ID: {patient.national_id}",
        f"Visit ID: {visit.id}",
        f"Payment ID: {payment.id}",
        f"Service: {payment.service_type}",
        f"Amount Paid: KES {payment.amount}",
        f"Payment Method: {payment.payment_method}",
    ]

    if payment.mpesa_receipt:
        info_lines.append(f"Mpesa Receipt: {payment.mpesa_receipt}")

    info_lines.append(f"Date: {payment.created_at.strftime('%Y-%m-%d %H:%M')}")

    for line in info_lines:
        pdf.drawString(70, y, line)
        y -= line_height

    # Footer
    y -= 30
    pdf.setFont("Helvetica-Oblique", 10)
    pdf.drawCentredString(width / 2, y, "Thank you for your payment.")
    y -= 15
    pdf.drawCentredString(width / 2, y, "This is a system-generated receipt from Triple T.S. Mediclinic.")

    pdf.showPage()
    pdf.save()

    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename={patient.first_name}_receipt_{payment.id}.pdf'

    return response


# Session Resource classes
class Login(Resource):    
    def post(self):
        data = request.get_json()
        email = data.get('email')  
        password = data.get('password')

        if not email or not password:
            return {'message': 'Email and password are required'}, 400

        try:
            user = User.query.filter_by(email=email).first()
        except SQLAlchemyError:
            return {'error': 'Database error.'}, 500

        if not user or not user.check_password(password):
            return {'error': 'Invalid credentials'}, 401

        session['user_id'] = user.id
        session.permanent = True 
        return user.to_dict(), 200


class Logout(Resource):
    def delete(self):
        if 'user_id' in session:
            session.pop('user_id')
            return '', 204
        return {'message': 'No active session'}, 400


class CheckSession(Resource):
    def get(self):
        user_id = session.get('user_id')
        if user_id:
            user = User.query.get(user_id)
            if user:
                return user.to_dict(), 200
            return {'message': 'User not found'}, 404
        return {'message': 'Not logged in'}, 401
    
api.add_resource(Login, '/login')
api.add_resource(Logout, '/logout')
api.add_resource(CheckSession, '/check_session')

# USER MANAGEMENT ROUTES (Admin-only)
class Users(Resource):
   
    def get(self):
        users = [user.to_dict() for user in User.query.all()]
        return make_response(jsonify(users), 200)

  
    def post(self):
        data = request.get_json()

        # Role check
        if data.get('role') not in roles:
            return {'error': f"Invalid role. Must be one of: {roles}"}, 400

        # Email exists check
        if User.query.filter_by(email=data['email']).first():
            return {'error': 'Email already exists'}, 400

        try:
            new_user = User(
                first_name=data.get('first_name'),
                last_name=data.get('last_name'),
                email=data.get('email'),
                national_id=data.get('national_id'),
                phone_number=data.get('phone_number'),
                password=data.get('password'),
                role=data.get('role')
            )
            db.session.add(new_user)
            db.session.commit()

        except ValueError as ve:
            db.session.rollback()
            return {'error': str(ve)}, 400

        except IntegrityError:
            db.session.rollback()
            return {'error': 'Duplicate entry or DB constraint failed'}, 400

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 500

        return {'message': 'User successfully registered', 'user': new_user.to_dict()}, 201


class UserByID(Resource):
 
    def get(self, id):
        user = db.session.get(User, id)
        if not user:
            return {'message': 'User not found'}, 404
        return user.to_dict(), 200

  
    def patch(self, id):
        user = db.session.get(User, id)
        if not user:
            return {'error': 'User not found'}, 404

        data = request.get_json()

        # Role validation
        if 'role' in data and data['role'] not in roles:
            return {'error': f"Invalid role. Must be one of: {roles}"}, 400

        try:
            for key, value in data.items():
                setattr(user, key, value)

            db.session.commit()

        except ValueError as ve:
            db.session.rollback()
            return {'error': str(ve)}, 400

        except IntegrityError:
            db.session.rollback()
            return {'error': 'Duplicate entry or DB constraint failed'}, 400

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 500

        return {'message': 'User successfully updated', 'user': user.to_dict()}, 200


  
    def delete(self, id):
        user = db.session.get(User, id)
        if not user:
            return {'message': 'User not found'}, 404

        db.session.delete(user)
        db.session.commit()
        return {'message': f"User {id} deleted"}, 200



# Add routes to the API
api.add_resource(Users, '/users')
api.add_resource(UserByID, '/users/<int:id>')


# PATIENT MANAGEMENT ROUTES
class Patients(Resource):
    def get(self):
        patients = [patient.to_dict() for patient in Patient.query.all()]
        return make_response(jsonify(patients), 200)

    def post(self):
        data = request.get_json()

        try:
            dob_raw = data['dob']

            if isinstance(dob_raw, int):
                dob = datetime.strptime(str(dob_raw), "%Y%m%d").date()
            elif isinstance(dob_raw, str):
                dob = datetime.fromisoformat(dob_raw).date()
            else:
                raise ValueError("Invalid DOB format")
            
            new_patient = Patient(
                first_name=data['first_name'],
                last_name=data['last_name'],
                gender=data['gender'],
                dob=dob, 
                national_id=data.get('national_id'),
                phone_number=data.get('phone_number'),
                email=data.get('email'),
            )

            db.session.add(new_patient)
            db.session.commit()

            return {'message': 'Patient successfully created', 'patient': new_patient.to_dict()}, 201

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

class PatientByID(Resource):
    def get(self, id):
        patient = db.session.get(Patient, id)
        if not patient:
            return {'message': 'Patient not found'}, 404
        return make_response(jsonify(patient.to_dict()), 200)

    def patch(self, id):
        patient = db.session.get(Patient, id)
        if not patient:
            return {'message': 'Patient not found'}, 404

        data = request.get_json()

        if 'dob' in data:
            try:
                data['dob'] = datetime.fromisoformat(data['dob']).date()
            except Exception:
                return {'error': 'Invalid date format for dob. Use YYYY-MM-DD.'}, 400

        try:
            for key, value in data.items():
                setattr(patient, key, value)

            db.session.commit()
            return make_response(jsonify(patient.to_dict()), 200)

        except (ValueError, IntegrityError) as e:
            db.session.rollback()
            return {'error': str(e)}, 400

        except Exception as e:
            db.session.rollback()
            return {'error': 'An unexpected error occurred.'}, 500


api.add_resource(Patients, '/patients')
api.add_resource(PatientByID, '/patients/<int:id>')

# VISIT MANAGEMENT ROUTES
class Visits(Resource):
    def get(self):
        visits = [visit.to_dict() for visit in Visit.query.all()]
        return make_response(jsonify(visits), 200)

    def post(self):
        data = request.get_json()

        # Validate required fields
        if 'patient_id' not in data:
            return {'error': 'Patient ID is required'}, 400

        try:
            new_visit = Visit(
                patient_id=data['patient_id'],
                triage_id=data.get('triage_id'),
                consultation_id=data.get('consultation_id'),
                stage=data.get('stage', 'reception')
            )
            db.session.add(new_visit)
            db.session.commit()
            return {'message': 'Visit created successfully', 'visit': new_visit.to_dict()}, 201

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

class VisitByID(Resource):
    def get(self, id):
        visit = db.session.get(Visit, id)
        if not visit:
            return {'message': 'Visit not found'}, 404
        return make_response(jsonify(visit.to_dict()), 200)

    def patch(self, id):
        visit = db.session.get(Visit, id)
        if not visit:
            return {'message': 'Visit not found'}, 404

        data = request.get_json()
        for key, value in data.items():
            setattr(visit, key, value)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

        return make_response(jsonify(visit.to_dict()), 200)

    def delete(self, id):
        visit = db.session.get(Visit, id)
        if not visit:
            return {'message': 'Visit not found'}, 404

        db.session.delete(visit)
        db.session.commit()
        return {'message': f'Visit {id} deleted successfully'}, 200


api.add_resource(Visits, '/visits')
api.add_resource(VisitByID, '/visits/<int:id>')

# TRIAGE MANAGEMENT ROUTES
class TriageRecords(Resource):
    def get(self):
        triages = TriageRecord.query.all()
        return [triage.to_dict() for triage in triages], 200
    
    def post(self):
        data = request.get_json()

        try:
            # Validate required fields
            required_fields = ['patient_id', 'nurse_id', 'temperature', 'weight', 'height', 'blood_pressure', 'visit_id']
            for field in required_fields:
                if field not in data:
                    return {'error': f"{field} is required"}, 400

            # Create new triage record
            new_triage = TriageRecord(
                patient_id=data['patient_id'],
                nurse_id=data['nurse_id'],
                temperature=data['temperature'],
                weight=data['weight'],
                height=data['height'],
                blood_pressure=data['blood_pressure'],
                pulse_rate=data.get('pulse_rate'),
                notes=data.get('notes'),
            )

            db.session.add(new_triage)
            db.session.flush()  # get ID without committing

            # Link to visit
            visit = db.session.get(Visit, data['visit_id'])
            if not visit:
                db.session.rollback()
                return {'error': 'Visit not found'}, 404

            visit.triage_id = new_triage.id
            visit.stage = 'waiting_consultation'  # optionally update the stage

            db.session.commit()
            return {'message': 'Triage record created', 'triage': new_triage.to_dict()}, 201

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400


class TriageRecordByID(Resource):
    def get(self, id):
        triage = db.session.get(TriageRecord, id)
        if not triage:
            return {'message': 'Triage record not found'}, 404
        return triage.to_dict(), 200


    def patch(self, id):
        triage = db.session.get(TriageRecord, id)
        if not triage:
            return {'message': 'Triage record not found'}, 404

        data = request.get_json()
        for key, value in data.items():
            setattr(triage, key, value)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

        return triage.to_dict(), 200



    def delete(self, id):
        triage = db.session.get(TriageRecord, id)
        if not triage:
            return {'message': 'Triage record not found'}, 404

        db.session.delete(triage)
        db.session.commit()
        return {'message': f'Triage record {id} deleted'}, 200
    
api.add_resource(TriageRecords, '/triage_records')
api.add_resource(TriageRecordByID, '/triage_records/<int:id>')

# CONSULTATION MANAGEMENT ROUTES
class Consultations(Resource):
    def get(self):
        consultations = Consultation.query.all()
        return [c.to_dict() for c in consultations], 200


    def post(self):
        data = request.get_json()

        try:
            required_fields = ['patient_id', 'doctor_id', 'visit_id']
            for field in required_fields:
                if field not in data:
                    return {'error': f"{field} is required"}, 400

            consultation = Consultation(
              patient_id=data['patient_id'],
               doctor_id=data['doctor_id'],
              diagnosis=data.get('diagnosis'),
              notes=data.get('notes'),
              fee=200,
               chief_complain=data.get('chief_complain'),
              physical_exam=data.get('physical_exam'),
              systemic_exam=data.get('systemic_exam'),
        )


            db.session.add(consultation)
            db.session.flush()  # Get consultation.id before commit

            visit = db.session.get(Visit, data['visit_id'])
            if not visit:
                raise ValueError("Associated visit not found.")
            visit.consultation_id = consultation.id

            db.session.commit()
            return consultation.to_dict(), 201

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

class ConsultationByID(Resource):
    def get(self, id):
        consultation = db.session.get(Consultation, id)
        if not consultation:
            return {'message': 'Consultation not found'}, 404
        return consultation.to_dict(), 200

    def patch(self, id):
        consultation = db.session.get(Consultation, id)
        if not consultation:
            return {'message': 'Consultation not found'}, 404

        data = request.get_json()
        for key, value in data.items():
            setattr(consultation, key, value)

        try:
            db.session.commit()
            return consultation.to_dict(), 200
        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400


    def delete(self, id):
        consultation = db.session.get(Consultation, id)
        if not consultation:
            return {'message': 'Consultation not found'}, 404

        db.session.delete(consultation)
        db.session.commit()
        return {'message': f'Consultation {id} deleted'}, 200


api.add_resource(Consultations, '/consultations')
api.add_resource(ConsultationByID, '/consultations/<int:id>')

# TEST MANAGEMENT ROUTES
class TestRequests(Resource):
    def get(self):
        test_requests = TestRequest.query.all()
        return [tr.to_dict() for tr in test_requests], 200

    def post(self):
        data = request.get_json()
        try:
            # Require test_type_id always
            if 'test_type_id' not in data:
                return {'error': "test_type_id is required"}, 400

            # Require at least one parent (consultation_id or visit_id)
            if not data.get('consultation_id') and not data.get('visit_id'):
                return {'error': "Either consultation_id or visit_id is required"}, 400

            # Validate test_type
            test_type = db.session.get(TestType, data['test_type_id'])
            if not test_type:
                return {'error': "Invalid test_type_id"}, 400

            test_request = TestRequest(
                consultation_id=data.get('consultation_id'),
                visit_id=data.get('visit_id'),
                technician_id=data.get('technician_id'),
                test_type_id=data['test_type_id'],
                results=data.get('results'),
                notes=data.get('notes'),
                status=data.get('status', 'pending')
            )

            db.session.add(test_request)
            db.session.commit()
            return test_request.to_dict(), 201

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400


class TestRequestByID(Resource):
    def get(self, id):
        test_request = db.session.get(TestRequest, id)
        if not test_request:
            return {'message': 'Test request not found'}, 404
        return test_request.to_dict(), 200

    def patch(self, id):
        test_request = db.session.get(TestRequest, id)
        if not test_request:
            return {'message': 'Test request not found'}, 404

        data = request.get_json()
        try:
            if "test_type_id" in data:
                # Validate test type exists
                test_type = db.session.get(TestType, data["test_type_id"])
                if not test_type:
                    return {"error": "Invalid test_type_id"}, 400
                test_request.test_type_id = data["test_type_id"]

            if "technician_id" in data:
                test_request.technician_id = data["technician_id"]

            if "results" in data:
                test_request.results = data["results"]

            if "notes" in data:
                test_request.notes = data["notes"]

            if "status" in data:
                test_request.status = data["status"]

            db.session.commit()
            return test_request.to_dict(), 200
        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

    def delete(self, id):
        test_request = db.session.get(TestRequest, id)
        if not test_request:
            return {'message': 'Test request not found'}, 404

        db.session.delete(test_request)
        db.session.commit()
        return {'message': f'Test request {id} deleted'}, 200


api.add_resource(TestRequests, '/test_requests')
api.add_resource(TestRequestByID, '/test_requests/<int:id>')

class TestTypes(Resource):
    def get(self):
        test_types = TestType.query.all()
        return [tt.to_dict() for tt in test_types], 200

    def post(self):
        data = request.get_json()
        try:
            required_fields = ['name', 'price', 'category']
            for field in required_fields:
                if field not in data:
                    return {'error': f"{field} is required"}, 400

            test_type = TestType(
                name=data['name'],
                price=data['price'],
                category=data['category']
            )

            db.session.add(test_type)
            db.session.commit()
            return test_type.to_dict(), 201

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400


class TestTypeByID(Resource):
    def get(self, id):
        test_type = db.session.get(TestType, id)
        if not test_type:
            return {'message': 'Test type not found'}, 404
        return test_type.to_dict(), 200

    def patch(self, id):
        test_type = db.session.get(TestType, id)
        if not test_type:
            return {'message': 'Test type not found'}, 404

        data = request.get_json()
        try:
            if "name" in data:
                test_type.name = data["name"]

            if "price" in data:
                test_type.price = data["price"]

            if "category" in data:
                test_type.category = data["category"]

            db.session.commit()
            return test_type.to_dict(), 200
        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

    def delete(self, id):
        test_type = db.session.get(TestType, id)
        if not test_type:
            return {'message': 'Test type not found'}, 404

        db.session.delete(test_type)
        db.session.commit()
        return {'message': f'Test type {id} deleted'}, 200



# Register routes
api.add_resource(TestTypes, '/test_types')
api.add_resource(TestTypeByID, '/test_types/<int:id>')


# ===========================
# MEDICINE MANAGEMENT ROUTES
# ===========================
class Medicines(Resource):
    def get(self):
        medicines = Medicine.query.all()
        return [m.to_dict() for m in medicines], 200

    def post(self):
        data = request.get_json()
        try:
            required_fields = ['name', 'buying_price', 'selling_price', 'unit']
            for field in required_fields:
                if field not in data:
                    return {'error': f"{field} is required"}, 400

            # ✅ Prevent duplicate names
            existing = Medicine.query.filter_by(name=data['name']).first()
            if existing:
                return {'error': 'Medicine with this name already exists'}, 400

            medicine = Medicine(
                name=data['name'],
                stock=data.get('stock', 0),
                sold_units=data.get('sold_units', 0),  # ✅ include sold_units
                buying_price=data['buying_price'],
                selling_price=data['selling_price'],
                unit=data['unit']
            )

            db.session.add(medicine)
            db.session.commit()
            return medicine.to_dict(), 201

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400


class MedicineByID(Resource):
    def get(self, id):
        medicine = db.session.get(Medicine, id)
        if not medicine:
            return {'message': 'Medicine not found'}, 404
        return medicine.to_dict(), 200

    def patch(self, id):
        medicine = db.session.get(Medicine, id)
        if not medicine:
            return {'message': 'Medicine not found'}, 404

        data = request.get_json()
        try:
            if "name" in data:
                existing = Medicine.query.filter(Medicine.name == data["name"], Medicine.id != id).first()
                if existing:
                    return {'error': 'Another medicine with this name already exists'}, 400
                medicine.name = data["name"]

            if "stock" in data:
                medicine.stock = data["stock"]

            if "sold_units" in data:  # ✅ allow updating sold_units
                medicine.sold_units = data["sold_units"]

            if "buying_price" in data:
                medicine.buying_price = data["buying_price"]

            if "selling_price" in data:
                medicine.selling_price = data["selling_price"]

            if "unit" in data:
                medicine.unit = data["unit"]

            db.session.commit()
            return medicine.to_dict(), 200

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

    def delete(self, id):
        medicine = db.session.get(Medicine, id)
        if not medicine:
            return {'message': 'Medicine not found'}, 404

        db.session.delete(medicine)
        db.session.commit()
        return {'message': f'Medicine {id} deleted'}, 200


# ✅ Register routes
api.add_resource(Medicines, '/medicines')
api.add_resource(MedicineByID, '/medicines/<int:id>')



# PRESCRIPTION MANAGEMENT ROUTES
class Prescriptions(Resource):
    def get(self):
        prescriptions = Prescription.query.all()
        return [p.to_dict() for p in prescriptions], 200

    def post(self):
        data = request.get_json()
        try:
            # Required fields
            required_fields = ['consultation_id', 'medicine_id', 'dosage']
            for field in required_fields:
                if field not in data:
                    return {'error': f"{field} is required"}, 400

            # Ensure medicine exists
            medicine = db.session.get(Medicine, data['medicine_id'])
            if not medicine:
                return {'error': "Medicine not found"}, 404

            dispensed_units = data.get('dispensed_units', 0)

            prescription = Prescription(
                consultation_id=data['consultation_id'],
                pharmacist_id=data.get('pharmacist_id'),
                medicine_id=data['medicine_id'],
                dosage=data['dosage'],
                instructions=data.get('instructions'),
                status=data.get('status', 'pending'),
                dispensed_units=dispensed_units
            )

            # Update medicine sold_units and stock if dispensed
            if dispensed_units > 0:
                medicine.stock -= dispensed_units
                medicine.sold_units = (medicine.sold_units or 0) + dispensed_units

            db.session.add(prescription)
            db.session.commit()
            return prescription.to_dict(), 201

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400


class PrescriptionByID(Resource):
    def get(self, id):
        prescription = db.session.get(Prescription, id)
        if not prescription:
            return {'message': 'Prescription not found'}, 404
        return prescription.to_dict(), 200

    def patch(self, id):
        prescription = db.session.get(Prescription, id)
        if not prescription:
            return {'message': 'Prescription not found'}, 404

        data = request.get_json()

        # Validate medicine if being updated
        if "medicine_id" in data:
            medicine = db.session.get(Medicine, data["medicine_id"])
            if not medicine:
                return {"error": "Medicine not found"}, 404

        # Track old dispensed_units to update stock/sold_units
        old_dispensed = prescription.dispensed_units or 0
        new_dispensed = data.get('dispensed_units', old_dispensed)

        for key, value in data.items():
            setattr(prescription, key, value)

        try:
            # Update medicine stock and sold_units if dispensed_units changed
            if new_dispensed != old_dispensed:
                med = prescription.medicine
                diff = new_dispensed - old_dispensed
                med.stock -= diff
                med.sold_units = (med.sold_units or 0) + diff

            db.session.commit()
            return prescription.to_dict(), 200
        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

    def delete(self, id):
        prescription = db.session.get(Prescription, id)
        if not prescription:
            return {'message': 'Prescription not found'}, 404

        # Optionally restore stock if prescription was dispensed
        if prescription.dispensed_units:
            med = prescription.medicine
            med.stock += prescription.dispensed_units
            med.sold_units = (med.sold_units or 0) - prescription.dispensed_units

        db.session.delete(prescription)
        db.session.commit()
        return {'message': f'Prescription {id} deleted'}, 200


# Register routes
api.add_resource(Prescriptions, '/prescriptions')
api.add_resource(PrescriptionByID, '/prescriptions/<int:id>')


# GET /payments, POST /payments
class Payments(Resource):
    def get(self):
        payments = Payment.query.all()
        return [p.to_dict() for p in payments], 200

    def post(self):
        data = request.get_json()

        try:
            # Must have EITHER visit_id or otc_sale_id
            if not data.get("visit_id") and not data.get("otc_sale_id"):
                return {"error": "Either visit_id or otc_sale_id is required"}, 400

            if data.get("visit_id") and data.get("otc_sale_id"):
                return {"error": "Provide only one of visit_id or otc_sale_id, not both"}, 400

            required_fields = ['receptionist_id', 'amount', 'service_type', 'payment_method']
            for field in required_fields:
                if field not in data:
                    return {'error': f"{field} is required"}, 400

            payment = Payment(
                visit_id=data.get('visit_id'),
                otc_sale_id=data.get('otc_sale_id'),
                amount=data['amount'],
                service_type=data['service_type'],
                payment_method=data['payment_method'],
                mpesa_receipt=data.get('mpesa_receipt'),
                receptionist_id=data['receptionist_id'],
            )

            db.session.add(payment)
            db.session.commit()
            return payment.to_dict(), 201

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

# GET /payments/<id>, PATCH /payments/<id>, DELETE /payments/<id>
class PaymentByID(Resource):
    def get(self, id):
        payment = db.session.get(Payment, id)
        if not payment:
            return {'message': 'Payment not found'}, 404
        return payment.to_dict(), 200

    def patch(self, id):
        payment = db.session.get(Payment, id)
        if not payment:
            return {'message': 'Payment not found'}, 404

        data = request.get_json()
        try:
            for key, value in data.items():
                setattr(payment, key, value)
            db.session.commit()
            return payment.to_dict(), 200
        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400

    def delete(self, id):
        payment = db.session.get(Payment, id)
        if not payment:
            return {'message': 'Payment not found'}, 404

        db.session.delete(payment)
        db.session.commit()
        return {'message': f'Payment {id} deleted'}, 200

api.add_resource(Payments, '/payments')
api.add_resource(PaymentByID, '/payments/<int:id>')

# --- OTC Sales Management Routes ---
class OTCSales(Resource):
    def get(self):
        sales = OTCSale.query.all()
        return [s.to_dict() for s in sales], 200

    def post(self):
        data = request.get_json()
        try:
            if "patient_name" not in data:
                return {"error": "patient_name is required"}, 400

            otc_sale = OTCSale(
                patient_name=data["patient_name"],
                stage=data.get("stage", "waiting_pharmacy"),
            )

            db.session.add(otc_sale)
            db.session.commit()
            return otc_sale.to_dict(), 201

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400


class OTCSaleByID(Resource):
    def get(self, id):
        sale = db.session.get(OTCSale, id)
        if not sale:
            return {"message": "OTC sale not found"}, 404
        return sale.to_dict(), 200

    def patch(self, id):
        sale = db.session.get(OTCSale, id)
        if not sale:
            return {"message": "OTC sale not found"}, 404

        data = request.get_json()
        try:
            if "patient_name" in data:
                sale.patient_name = data["patient_name"]

            if "stage" in data:
                sale.stage = data["stage"]

            db.session.commit()
            return sale.to_dict(), 200

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400

    def delete(self, id):
        sale = db.session.get(OTCSale, id)
        if not sale:
            return {"message": "OTC sale not found"}, 404

        db.session.delete(sale)
        db.session.commit()
        return {"message": f"OTC sale {id} deleted"}, 200


# --- Pharmacy Sales Management Routes ---
class PharmacySales(Resource):
    def get(self):
        sales = PharmacySale.query.all()
        return [s.to_dict() for s in sales], 200

    def post(self):
        data = request.get_json()
        try:
            required_fields = ["otc_sale_id", "pharmacist_id", "medicine_id", "dispensed_units"]
            for field in required_fields:
                if field not in data:
                    return {"error": f"{field} is required"}, 400

            # Ensure medicine exists
            medicine = db.session.get(Medicine, data["medicine_id"])
            if not medicine:
                return {"error": "Medicine not found"}, 404

            dispensed_units = int(data.get("dispensed_units", 1))

            # Update stock + sold units
            if medicine.stock < dispensed_units:
                return {"error": "Not enough stock available"}, 400

            medicine.stock -= dispensed_units
            medicine.sold_units = (medicine.sold_units or 0) + dispensed_units

            sale = PharmacySale(
                otc_sale_id=data["otc_sale_id"],
                pharmacist_id=data["pharmacist_id"],
                medicine_id=data["medicine_id"],
                dispensed_units=dispensed_units,
            )

            db.session.add(sale)
            db.session.commit()
            return sale.to_dict(), 201

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400


class PharmacySaleByID(Resource):
    def get(self, id):
        sale = db.session.get(PharmacySale, id)
        if not sale:
            return {"message": "Pharmacy sale not found"}, 404
        return sale.to_dict(), 200

    def patch(self, id):
        sale = db.session.get(PharmacySale, id)
        if not sale:
            return {"message": "Pharmacy sale not found"}, 404

        data = request.get_json()
        old_units = sale.dispensed_units
        new_units = int(data.get("dispensed_units", old_units))

        try:
            # Update stock if dispensed_units changed
            if new_units != old_units:
                med = sale.medicine
                diff = new_units - old_units

                if diff > 0 and med.stock < diff:
                    return {"error": "Not enough stock available"}, 400

                med.stock -= diff
                med.sold_units = (med.sold_units or 0) + diff

            # Apply updates
            for key, value in data.items():
                setattr(sale, key, value)

            db.session.commit()
            return sale.to_dict(), 200

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400

    def delete(self, id):
        sale = db.session.get(PharmacySale, id)
        if not sale:
            return {"message": "Pharmacy sale not found"}, 404

        # Restore stock
        med = sale.medicine
        med.stock += sale.dispensed_units
        med.sold_units = (med.sold_units or 0) - sale.dispensed_units

        db.session.delete(sale)
        db.session.commit()
        return {"message": f"Pharmacy sale {id} deleted"}, 200


# Register routes
api.add_resource(OTCSales, "/otc_sales")
api.add_resource(OTCSaleByID, "/otc_sales/<int:id>")
api.add_resource(PharmacySales, "/pharmacy_sales")
api.add_resource(PharmacySaleByID, "/pharmacy_sales/<int:id>")

# ===========================
# PHARMACY EXPENSES ROUTES
# ===========================
class PharmacyExpenses(Resource):
    def get(self):
        """Return all pharmacy expenses"""
        expenses = PharmacyExpense.query.all()
        return [e.to_dict() for e in expenses], 200

    def post(self):
        """Add a new pharmacy expense and update medicine stock"""
        data = request.get_json()
        try:
            required_fields = ["medicine_id", "quantity_added"]
            for field in required_fields:
                if field not in data:
                    return {"error": f"{field} is required"}, 400

            medicine = db.session.get(Medicine, data["medicine_id"])
            if not medicine:
                return {"error": "Medicine not found"}, 404

            quantity = int(data["quantity_added"])
            if quantity <= 0:
                return {"error": "Quantity added must be greater than 0"}, 400

            discount = float(data.get("discount", 0.0))
            if discount < 0:
                return {"error": "Discount must be positive"}, 400

            # Create expense
            expense = PharmacyExpense(medicine=medicine, quantity_added=quantity, discount=discount)

            # Update medicine stock
            medicine.stock += quantity

            db.session.add(expense)
            db.session.commit()
            return expense.to_dict(), 201

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400


class PharmacyExpenseByID(Resource):
    def get(self, id):
        expense = db.session.get(PharmacyExpense, id)
        if not expense:
            return {"message": "Pharmacy expense not found"}, 404
        return expense.to_dict(), 200

    def patch(self, id):
        expense = db.session.get(PharmacyExpense, id)
        if not expense:
            return {"message": "Pharmacy expense not found"}, 404

        data = request.get_json()
        try:
            medicine = expense.medicine

            if "quantity_added" in data:
                new_quantity = int(data["quantity_added"])
                if new_quantity <= 0:
                    return {"error": "Quantity must be greater than 0"}, 400

                diff = new_quantity - expense.quantity_added
                medicine.stock += diff
                expense.quantity_added = new_quantity

            if "discount" in data:
                new_discount = float(data["discount"])
                if new_discount < 0:
                    return {"error": "Discount must be positive"}, 400
                expense.discount = new_discount

            # Recalculate total cost after any change
            expense.total_cost = expense.calculate_total()

            db.session.commit()
            return expense.to_dict(), 200

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400


# ✅ Register the new routes
api.add_resource(PharmacyExpenses, "/pharmacy_expenses")
api.add_resource(PharmacyExpenseByID, "/pharmacy_expenses/<int:id>")

class AdminAnalytics(Resource):
    def get(self):
        today = datetime.utcnow()
        first_day_month = today.replace(day=1)

        # --- 1. Metrics Cards ---
        total_patients = Patient.query.count()
        patients_this_month = Patient.query.filter(Patient.created_at >= first_day_month).count()

        # all revenue (all payments ever)
        all_revenue = db.session.query(
            func.coalesce(func.sum(Payment.amount), 0)
        ).scalar()

        # this month's revenue
        total_revenue_past_month = db.session.query(
            func.coalesce(func.sum(Payment.amount), 0)
        ).filter(Payment.created_at >= first_day_month).scalar()
        

        lab_tests_done = (
            db.session.query(func.count(TestRequest.id))
            .join(TestType, TestRequest.test_type_id == TestType.id)
            .filter(TestType.category == "lab", TestRequest.created_at >= first_day_month)
            .scalar()
        )

        imaging_tests_done = (
            db.session.query(func.count(TestRequest.id))
            .join(TestType, TestRequest.test_type_id == TestType.id)
            .filter(TestType.category == "imaging", TestRequest.created_at >= first_day_month)
            .scalar()
        )

        # --- 3. Pharmacy Sales Breakdown ---
        otc_revenue = db.session.query(func.coalesce(func.sum(Payment.amount), 0)) \
            .filter(Payment.service_type == "OTC Sale", Payment.created_at >= first_day_month).scalar()
        prescription_revenue = (
            db.session.query(
                func.coalesce(func.sum(Prescription.dispensed_units * Medicine.selling_price), 0)
            )
            .join(Medicine, Prescription.medicine_id == Medicine.id)
            .filter(Prescription.created_at >= first_day_month)
            .scalar()
        )

        pharmacy_breakdown = {
            "Over The Counter": float(otc_revenue),
            "Prescription": float(prescription_revenue)
        }
        # ✅ Now calculate total from breakdown
        total_pharmacy_sales = float(otc_revenue) + float(prescription_revenue)

        # --- 4. Pharmacy Expenses (this month only) ---
        recent_expenses = PharmacyExpense.query \
            .filter(PharmacyExpense.created_at >= first_day_month) \
            .order_by(PharmacyExpense.created_at.desc()) \
            .limit(10).all()

        expenses_list = [
            {
                "date": e.created_at.strftime("%Y-%m-%d"),
                "medicine": e.medicine.name,
                "quantity_added": e.quantity_added,
                "discount":e.discount,
                "total_cost": e.total_cost
            } for e in recent_expenses
        ]

        # --- 5. Top 10 Prescribed Medicines (this month only) ---
        top_medicines = (
            db.session.query(
                Medicine.name,
                func.coalesce(func.sum(Prescription.dispensed_units), 0).label("total_units")
            )
            .join(Prescription, Prescription.medicine_id == Medicine.id)
            .filter(Prescription.created_at >= first_day_month)
            .group_by(Medicine.id)
            .order_by(func.sum(Prescription.dispensed_units).desc())
            .limit(10)
            .all()
        )
        top_medicines_list = [{"medicine": m[0], "total_units": int(m[1])} for m in top_medicines]

        # --- 6. Low Stock Medicines (no date filter, always current) ---
        low_stock_meds = Medicine.query.filter(Medicine.stock < 5).all()
        low_stock_list = [{"medicine": m.name, "stock": m.stock} for m in low_stock_meds]

        # --- 7. Top 5 Lab & Imaging Tests (this month only) ---
        top_lab_tests = (
            db.session.query(TestType.name, func.count(TestRequest.id).label("count"))
            .join(TestRequest, TestRequest.test_type_id == TestType.id)
            .filter(TestType.category == "lab", TestRequest.created_at >= first_day_month)
            .group_by(TestType.id)
            .order_by(func.count(TestRequest.id).desc())
            .limit(5)
            .all()
        )
        top_lab_list = [{"test": t[0], "count": t[1]} for t in top_lab_tests]

        top_imaging_tests = (
            db.session.query(TestType.name, func.count(TestRequest.id).label("count"))
            .join(TestRequest, TestRequest.test_type_id == TestType.id)
            .filter(TestType.category == "imaging", TestRequest.created_at >= first_day_month)
            .group_by(TestType.id)
            .order_by(func.count(TestRequest.id).desc())
            .limit(5)
            .all()
        )
        top_imaging_list = [{"test": t[0], "count": t[1]} for t in top_imaging_tests]

        return jsonify({
        "metrics": {
            "all_revenue": float(all_revenue),
            "total_revenue_past_month": float(total_revenue_past_month),
            "total_pharmacy_sales": float(total_pharmacy_sales),
            "total_patients": total_patients,
            "patients_this_month": patients_this_month,
            "lab_tests_done": lab_tests_done,
            "imaging_tests_done": imaging_tests_done
        },
        "pharmacy_breakdown": pharmacy_breakdown,
        "recent_expenses": expenses_list,
        "top_medicines": top_medicines_list,
        "low_stock_medicines": low_stock_list,
        "top_lab_tests": top_lab_list,
        "top_imaging_tests": top_imaging_list
    })


api.add_resource(AdminAnalytics, "/analytics")



if __name__ == '__main__':
    with app.app_context():
        app.run(port=5050, debug=True)


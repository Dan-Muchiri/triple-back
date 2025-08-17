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
from models import db, User, roles, Patient, Visit, TriageRecord, Consultation, TestRequest, Prescription, Payment, TestType, Medicine
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

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
            required_fields = ['test_type_id']
            for field in required_fields:
                if field not in data:
                    return {'error': f"{field} is required"}, 400

            # Make sure the test type exists
            test_type = db.session.get(TestType, data['test_type_id'])
            if not test_type:
                return {'error': "Invalid test_type_id"}, 400

            test_request = TestRequest(
                consultation_id=data['consultation_id'],
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
            # Required field
            if 'test_type_id' not in data:
                return {'error': 'test_type_id is required'}, 400

            # Validate test type
            test_type = db.session.get(TestType, data['test_type_id'])
            if not test_type:
                return {'error': "Invalid test_type_id"}, 400

            # Optional: link to consultation or visit
            consultation_id = data.get('consultation_id')
            visit_id = data.get('visit_id')  # new optional field for direct visit

            if not consultation_id and not visit_id:
                return {'error': 'Either consultation_id or visit_id must be provided'}, 400

            # If linked to visit directly, ensure visit exists
            visit = None
            if visit_id:
                visit = db.session.get(Visit, visit_id)
                if not visit:
                    return {'error': 'Invalid visit_id'}, 400
                consultation_id = None  # Ensure it's null for direct visit

            test_request = TestRequest(
                consultation_id=consultation_id,
                technician_id=data.get('technician_id'),
                test_type_id=data['test_type_id'],
                results=data.get('results'),
                notes=data.get('notes'),
                status=data.get('status', 'pending')
            )

            db.session.add(test_request)
            db.session.commit()

            # Optionally attach to visit for frontend convenience
            if visit:
                visit.test_requests_direct.append(test_request)
                db.session.commit()

            return test_request.to_dict(), 201

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
            required_fields = ['visit_id', 'receptionist_id', 'amount', 'service_type', 'payment_method']
            for field in required_fields:
                if field not in data:
                    return {'error': f"{field} is required"}, 400

            payment = Payment(
                visit_id=data['visit_id'],
                amount=data['amount'],
                service_type=data['service_type'],
                payment_method=data['payment_method'],
                mpesa_receipt=data.get('mpesa_receipt'),
                receptionist_id=data['receptionist_id'],
                test_request_id=data.get('test_request_id'),
                prescription_id=data.get('prescription_id'),
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


if __name__ == '__main__':
    with app.app_context():
        app.run(port=5050, debug=True)


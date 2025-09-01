from flask import Flask, jsonify, request, make_response, session, abort
from flask_restful import Resource,Api
import os
import re
from dotenv import load_dotenv
from flask_cors import CORS
from flask_migrate import Migrate
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import IntegrityError
from marshmallow import ValidationError
from models import db, User, roles, Patient, Visit, TriageRecord, Consultation, TestRequest, Prescription, Payment, TestType, Medicine, PharmacySale, OTCSale, PharmacyExpense,LeaveOff
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
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

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    styles = getSampleStyleSheet()
    title_style = styles['Title']
    normal = styles['Normal']

    # Header
    elements.append(Paragraph("TRIPLE T.S. MEDICLINIC", title_style))
    elements.append(Paragraph("OFFICIAL RECEIPT", styles['Heading2']))
    elements.append(Spacer(1, 20))

    # --- Case 1: Visit Payment ---
    if payment.visit:
        visit = payment.visit
        patient = visit.patient

        patient_info = [
            f"Patient: {patient.first_name} {patient.last_name}",
            f"National ID: {patient.national_id}",
            f"Visit ID: {visit.id}",
            f"Payment ID: {payment.id}",
            f"Payment Method: {payment.payment_method}",
            f"Date: {payment.created_at.strftime('%Y-%m-%d %H:%M')}"
        ]
        if payment.mpesa_receipt:
            patient_info.append(f"Mpesa Receipt: {payment.mpesa_receipt}")

        for line in patient_info:
            elements.append(Paragraph(line, normal))
        elements.append(Spacer(1, 15))

        # Services Table (accurate from visit)
        service_data = [["Service", "Amount (KES)"]]

        # Consultation fee
        if visit.consultation:
            service_data.append(["Consultation", f"{visit.consultation.fee:,.2f}"])

            # Prescriptions
            for p in visit.consultation.prescriptions:
                med_name = p.medicine.name if p.medicine else "Unknown"
                qty = p.dispensed_units or 0
                price = p.total_price or (qty * (p.medicine.selling_price if p.medicine else 0))
                service_data.append([f"Prescription: {med_name} x {qty}", f"{price:,.2f}"])

            # Test requests
            for tr in visit.consultation.test_requests:
                service_data.append([f"Test: {tr.test_type.name}", f"{tr.amount:,.2f}"])

        # Direct test requests (not linked to consultation)
        for tr in visit.test_requests:
            service_data.append([f"Test: {tr.test_type.name}", f"{tr.amount:,.2f}"])

        total_charges = visit.total_charges
        col_widths = [300, 150]  # 2-column layout for visit

    # --- Case 2: OTC Payment ---
    elif payment.otc_sale:
        otc_sale = payment.otc_sale

        otc_info = [
            f"Customer: {otc_sale.patient_name}",
            f"OTC Sale ID: {otc_sale.id}",
            f"Payment ID: {payment.id}",
            f"Payment Method: {payment.payment_method}",
            f"Date: {payment.created_at.strftime('%Y-%m-%d %H:%M')}"
        ]
        if payment.mpesa_receipt:
            otc_info.append(f"Mpesa Receipt: {payment.mpesa_receipt}")

        for line in otc_info:
            elements.append(Paragraph(line, normal))
        elements.append(Spacer(1, 15))

        # OTC Sales Table
        service_data = [["Medicine", "Qty", "Unit Price (KES)", "Total (KES)"]]
        for sale in otc_sale.sales:
            med_name = sale.medicine.name if sale.medicine else "N/A"
            service_data.append([
                Paragraph(med_name, normal),  # wrapped medicine name
                sale.dispensed_units,
                f"{sale.medicine.selling_price:,.2f}" if sale.medicine else "0.00",
                f"{sale.total_price:,.2f}"
            ])

        total_charges = otc_sale.total_price
        col_widths = [200, 50, 100, 100]  # 4-column layout for OTC

    else:
        abort(400, "Payment not linked to a Visit or OTC Sale")

    # Build the table
    table = Table(service_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),  # left align first column, center numbers
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 15))

    # Totals
    elements.append(Paragraph(f"<b>Total Charges: KES {total_charges:,.2f}</b>", styles['Heading3']))
    elements.append(Paragraph(f"<b>Paid Now: KES {payment.amount:,.2f}</b>", styles['Heading3']))

    # If part payment, show balance
    if payment.visit:
        balance = visit.balance
    elif payment.otc_sale:
        balance = otc_sale.balance
    else:
        balance = 0

    elements.append(Paragraph(f"<b>Balance: KES {balance:,.2f}</b>", styles['Heading3']))
    elements.append(Spacer(1, 20))

    # Footer
    elements.append(Paragraph("Thank you for your payment.", styles['Italic']))
    elements.append(Paragraph("This is a system-generated receipt from Triple T.S. Mediclinic.", styles['Italic']))

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    # Filename safe generation
    if payment.visit:
        first_name = payment.visit.patient.first_name or "Patient"
        last_name = payment.visit.patient.last_name or ""
    elif payment.otc_sale:
        first_name = payment.otc_sale.patient_name or "Customer"
        last_name = ""
    else:
        first_name, last_name = "Unknown", ""

    safe_first = re.sub(r'[^A-Za-z0-9]+', '_', first_name)
    safe_last = re.sub(r'[^A-Za-z0-9]+', '_', last_name)

    filename = f"{safe_first}_{safe_last}_receipt_{payment.id}.pdf"

    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
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

# LEAVEOFF MANAGEMENT ROUTES
class LeaveOffs(Resource):

    def get(self):
        leaveoffs = [lo.to_dict() for lo in LeaveOff.query.all()]
        return make_response(jsonify(leaveoffs), 200)

    def post(self):
        data = request.get_json()

        # Ensure user exists
        user = db.session.get(User, data.get('user_id'))
        if not user:
            return {'error': 'User not found'}, 404

        try:
            start_str = data.get("start_datetime").replace("Z", "+00:00")
            end_str = data.get("end_datetime").replace("Z", "+00:00")

            new_leaveoff = LeaveOff(
                user_id=data.get("user_id"),
                start_datetime=datetime.fromisoformat(start_str),
                end_datetime=datetime.fromisoformat(end_str),
)
            db.session.add(new_leaveoff)
            db.session.commit()

        except ValueError as ve:
            db.session.rollback()
            return {'error': str(ve)}, 400

        except IntegrityError:
            db.session.rollback()
            return {'error': 'Database constraint failed'}, 400

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 500

        return {
            'message': 'Leave/Off successfully created',
            'leaveoff': new_leaveoff.to_dict()
        }, 201


class LeaveOffByID(Resource):

    def get(self, id):
        leaveoff = db.session.get(LeaveOff, id)
        if not leaveoff:
            return {'message': 'Leave/Off not found'}, 404
        return leaveoff.to_dict(), 200

    def patch(self, id):
        leaveoff = db.session.get(LeaveOff, id)
        if not leaveoff:
            return {'error': 'Leave/Off not found'}, 404

        data = request.get_json()
        try:
            for key, value in data.items():
                if key == "start_datetime":
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))

                if key == "end_datetime":
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))

                setattr(leaveoff, key, value)

            db.session.commit()

        except ValueError as ve:
            db.session.rollback()
            return {'error': str(ve)}, 400

        except IntegrityError:
            db.session.rollback()
            return {'error': 'Database constraint failed'}, 400

        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 500

        return {
            'message': 'Leave/Off successfully updated',
            'leaveoff': leaveoff.to_dict()
        }, 200


    def delete(self, id):
        leaveoff = db.session.get(LeaveOff, id)
        if not leaveoff:
            return {'message': 'Leave/Off not found'}, 404

        db.session.delete(leaveoff)
        db.session.commit()
        return {'message': f"Leave/Off {id} deleted"}, 200


# Add routes to the API
api.add_resource(LeaveOffs, '/leaveoffs')
api.add_resource(LeaveOffByID, '/leaveoffs/<int:id>')



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
                next_of_kin_phone=data.get('next_of_kin_phone'),
                location=data.get('location')
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
                if hasattr(patient, key):
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

        # ✅ Check if medicine is linked to any expenses
        if medicine.expenses and len(medicine.expenses) > 0:
            return {
                'message': 'You cannot delete this medicine because it has related expenses.'
            }, 400

        try:
            db.session.delete(medicine)
            db.session.commit()
            return {'message': f'Medicine {id} deleted successfully'}, 200
        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 400



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
            required_fields = ["otc_sale_id", "pharmacist_id", "medicine_id", "dispensed_units", "total_price"]
            for field in required_fields:
                if field not in data:
                    return {"error": f"{field} is required"}, 400

            # Ensure medicine exists
            medicine = db.session.get(Medicine, data["medicine_id"])
            if not medicine:
                return {"error": "Medicine not found"}, 404

            dispensed_units = int(data["dispensed_units"])

            if dispensed_units <= 0:
                return {"error": "Dispensed units must be greater than 0"}, 400

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
                total_price=float(data["total_price"])  # now provided manually
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
                sale.dispensed_units = new_units

            # Allow manual update of total_price
            if "total_price" in data:
                sale.total_price = float(data["total_price"])

            # Other fields
            if "pharmacist_id" in data:
                sale.pharmacist_id = data["pharmacist_id"]

            if "medicine_id" in data:
                med = db.session.get(Medicine, data["medicine_id"])
                if not med:
                    return {"error": "Medicine not found"}, 404
                sale.medicine_id = med.id

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
            required_fields = ["medicine_id", "quantity_added", "total_cost"]
            for field in required_fields:
                if field not in data:
                    return {"error": f"{field} is required"}, 400

            medicine = db.session.get(Medicine, data["medicine_id"])
            if not medicine:
                return {"error": "Medicine not found"}, 404

            quantity = int(data["quantity_added"])
            if quantity <= 0:
                return {"error": "Quantity added must be greater than 0"}, 400

            total_cost = float(data["total_cost"])
            if total_cost < 0:
                return {"error": "Total cost must be non-negative"}, 400

            # Create expense (manual total_cost)
            expense = PharmacyExpense(
                medicine=medicine,
                quantity_added=quantity,
                total_cost=total_cost
            )

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

            if "total_cost" in data:
                new_total = float(data["total_cost"])
                if new_total < 0:
                    return {"error": "Total cost must be non-negative"}, 400
                expense.total_cost = new_total

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


        # --- 5. Top 10 Medicines (Prescriptions + OTC Sales, this month only) ---
        # --- 5. Top 10 Medicines (Prescriptions + OTC Sales, this month only) ---
        prescription_query = (
            db.session.query(
                Medicine.name.label("medicine_name"),
                func.coalesce(func.sum(Prescription.dispensed_units), 0).label("total_units")
            )
            .join(Prescription, Prescription.medicine_id == Medicine.id)
            .filter(Prescription.created_at >= first_day_month)
            .group_by(Medicine.id)
        )

        pharmacy_query = (
            db.session.query(
                Medicine.name.label("medicine_name"),
                func.coalesce(func.sum(PharmacySale.dispensed_units), 0).label("total_units")
            )
            .join(PharmacySale, PharmacySale.medicine_id == Medicine.id)
            .filter(PharmacySale.created_at >= first_day_month)
            .group_by(Medicine.id)
        )

        # Combine with union
        union_q = prescription_query.union_all(pharmacy_query).subquery()

        # Aggregate again so same medicine merges
        combined_top = (
            db.session.query(
                union_q.c.medicine_name,
                func.sum(union_q.c.total_units).label("total_units")
            )
            .group_by(union_q.c.medicine_name)
            .order_by(func.sum(union_q.c.total_units).desc())
            .limit(10)
            .all()
        )

        top_medicines_list = [
            {"medicine": row.medicine_name, "total_units": int(row.total_units)}
            for row in combined_top
        ]



        # --- 7. Top 5 Lab & Imaging Tests (this month only) ---
        top_lab_tests = (
            db.session.query(TestType.name, func.count(TestRequest.id).label("count"))
            .join(TestRequest, TestRequest.test_type_id == TestType.id)
            .filter(TestType.category == "lab", TestRequest.created_at >= first_day_month)
            .group_by(TestType.id)
            .order_by(func.count(TestRequest.id).desc())
            .limit(10)
            .all()
        )
        top_lab_list = [{"test": t[0], "count": t[1]} for t in top_lab_tests]

        top_imaging_tests = (
            db.session.query(TestType.name, func.count(TestRequest.id).label("count"))
            .join(TestRequest, TestRequest.test_type_id == TestType.id)
            .filter(TestType.category == "imaging", TestRequest.created_at >= first_day_month)
            .group_by(TestType.id)
            .order_by(func.count(TestRequest.id).desc())
            .limit(10)
            .all()
        )
        top_imaging_list = [{"test": t[0], "count": t[1]} for t in top_imaging_tests]

        return jsonify({
        "metrics": {
            "all_revenue": float(all_revenue),
            "total_revenue_past_month": float(total_revenue_past_month),
            "total_patients": total_patients,
            "patients_this_month": patients_this_month,
            "lab_tests_done_this_month": lab_tests_done,          # (optional consistency)
            "imaging_tests_done_this_month": imaging_tests_done   # (optional consistency)
        },
        "top_medicines_this_month": top_medicines_list,
        "top_lab_tests_this_month": top_lab_list,
        "top_imaging_tests_this_month": top_imaging_list
    })



api.add_resource(AdminAnalytics, "/analytics")

@app.route('/pharmacy_all_sales', methods=['GET'])
def get_all_sales():
    data = []

    # Fetch all prescriptions with their visits
    prescriptions = (
        db.session.query(Prescription)
        .join(Prescription.consultation)
        .join(Consultation.visit)
        .all()
    )

    # Filter in Python: only fully paid visits
    for p in prescriptions:
        if p.consultation and p.consultation.visit and p.consultation.visit.balance == 0:
            data.append({
                "id": f"presc-{p.id}",
                "medicine": p.medicine.name if p.medicine else None,
                "buying_price": p.medicine.buying_price if p.medicine else None,
                "quantity": p.dispensed_units,
                "total": p.total_price,
                "type": "Prescription",
                "created_at": p.created_at.isoformat() if p.created_at else None
            })

    # Fetch all OTC sales with their parent
    otc_sales = (
        db.session.query(PharmacySale)
        .join(PharmacySale.otc_sale)
        .all()
    )

    # Filter in Python: only fully paid OTC sales
    for s in otc_sales:
        if s.otc_sale and s.otc_sale.balance == 0:
            data.append({
                "id": f"otc-{s.id}",
                "medicine": s.medicine.name if s.medicine else None,
                "buying_price": s.medicine.buying_price if s.medicine else None,
                "quantity": s.dispensed_units,
                "total": s.total_price,
                "type": "OTC",
                "created_at": s.created_at.isoformat() if s.created_at else None
            })

    # Sort by date DESC
    data.sort(key=lambda x: x["created_at"], reverse=True)

    return jsonify(data), 200






if __name__ == '__main__':
    with app.app_context():
        app.run(port=5050, debug=True)


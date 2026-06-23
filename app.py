from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient, UpdateOne
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import re
import uuid
import random
import os
import threading
import time
import base64
import json


# Load environment variables from local .env file if it exists
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(dotenv_path):
    print("Loading environment variables from local .env file...")
    with open(dotenv_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip()
                    # Strip quotes if present
                    if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                        val = val[1:-1]
                    os.environ[key] = val

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key_here_change_this_in_production')
CORS(app)

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '852109867543-exampleclientid.apps.googleusercontent.com')




# MongoDB Connection
MONGO_URI = os.environ.get('MONGO_URI', "mongodb+srv://admin123:admin123@cluster0.slklrau.mongodb.net/?appName=Cluster0")

client = None
db = None
staff_collection = None
attendance_collection = None

# Caching & dynamic collections initialization
initialized_student_collections = set()
stats_cache = {}
CACHE_TTL = timedelta(seconds=45)

def get_students_collection(staff_id):
    global initialized_student_collections
    col_name = f"staff_students_{staff_id}"
    col = db[col_name]
    if col_name not in initialized_student_collections:
        try:
            col.create_index('id', unique=True)
            col.create_index('phone')
            initialized_student_collections.add(col_name)
            print(f"Initialized indexes on collection: {col_name}")
        except Exception as e:
            print(f"Error creating indexes on {col_name}: {e}")
    return col

def get_cached_stats(cache_key, compute_func):
    now = datetime.now()
    if cache_key in stats_cache:
        entry = stats_cache[cache_key]
        if now < entry['expires_at']:
            print(f"CACHE HIT: Returning cached stats for {cache_key}")
            return entry['data']
    
    print(f"CACHE MISS: Computing stats for {cache_key}")
    data = compute_func()
    stats_cache[cache_key] = {
        'expires_at': now + CACHE_TTL,
        'data': data
    }
    return data

def invalidate_stats_cache(staff_id=None):
    global stats_cache
    if staff_id:
        stats_cache.pop(staff_id, None)
        stats_cache.pop('admin', None)
        print(f"CACHE INVALIDATED for staff: {staff_id} (and admin)")
    else:
        stats_cache.clear()
        print("CACHE INVALIDATED (all)")

def init_db():
    global client, db, staff_collection, attendance_collection
    try:
        # If client already exists, check if it is still alive by pinging
        if client is not None:
            try:
                client.admin.command('ping')
                return True
            except Exception:
                print("Existing MongoDB connection lost. Reconnecting...")
                client = None
        
        print("Connecting to MongoDB Atlas...")
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, maxPoolSize=50, minPoolSize=10)
        client.admin.command('ping')
        print("Connected to MongoDB Atlas successfully!")
        
        db = client['staff_management_system']
        
        # Collections
        staff_collection = db['staff_accounts']
        attendance_collection = db['attendance']
        
        # Create indexes safely
        def safe_create_index(collection, keys, **kwargs):
            try:
                collection.create_index(keys, **kwargs)
            except Exception as e:
                print(f"Warning: could not create index {keys} on {collection.name}: {e}")
                
        safe_create_index(staff_collection, 'username', unique=True)
        safe_create_index(staff_collection, 'staffId', unique=True)
        
        safe_create_index(attendance_collection, [('staffId', 1), ('date', 1)])
        safe_create_index(attendance_collection, 'id', unique=True)
        safe_create_index(attendance_collection, 'studentId')
        
        safe_create_index(db['ended_students'], [('staffId', 1), ('id', 1)])
        safe_create_index(db['staff_self_attendance'], [('staffId', 1), ('date', 1)], unique=True)
        
        safe_create_index(db['custom_class_slots'], [('studentId', 1), ('date', 1)])
        safe_create_index(db['custom_class_slots'], 'id')
        
        safe_create_index(db['no_class_audit_logs'], 'timestamp')
        
        print("All collections and indexes ready (without listing collections)")
        return True
        
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        client = None
        db = None
        staff_collection = None
        attendance_collection = None
        return False

# Initial connection attempt
init_db()



@app.before_request
def ensure_db_connected():
    global client, db
    # Only reconnect on API routes to avoid blocking static assets or simple pages
    if request.path.startswith('/api/') and request.path != '/api/health':
        if client is None or db is None:
            init_db()

def serialize_doc(doc):
    if doc and '_id' in doc:
        doc['_id'] = str(doc['_id'])
    return doc

def generate_username(full_name):
    """Generate username from full name (remove spaces, lowercase) - NO NUMBERS"""
    clean_name = re.sub(r'[^a-zA-Z\s]', '', full_name)
    username = clean_name.lower().replace(' ', '_')
    username = re.sub(r'[^a-z_]', '', username)
    return username

def generate_password(full_name):
    """Generate password: half of staff name + 3 random digits"""
    name_length = len(full_name)
    half_length = max(3, name_length // 2)
    half_name = full_name[:half_length].lower()
    half_name = half_name.replace(' ', '')
    half_name = re.sub(r'[^a-z]', '', half_name)
    random_digits = str(random.randint(100, 999))
    password = half_name + random_digits
    return password

def log_login_attempt(login_type, user_type, identifier, status, message):
    try:
        if db is not None:
            log_entry = {
                'timestamp': datetime.utcnow(),
                'login_type': login_type,
                'user_type': user_type,
                'identifier': identifier,
                'status': status,
                'ip_address': request.remote_addr,
                'user_agent': request.headers.get('User-Agent'),
                'message': message
            }
            db['login_logs'].insert_one(log_entry)
            print(f"[Login Log] {status.upper()}: {login_type} login for {user_type} ({identifier}) - {message}")
    except Exception as e:
        print(f"Failed to write login log: {e}")

# ==================================================
# LOGIN & AUTHENTICATION
# ==================================================

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({
        'google_client_id': GOOGLE_CLIENT_ID
    })

@app.route('/api/google-login', methods=['POST'])
def google_login():
    data = request.json
    token = data.get('credential')
    if not token:
        log_login_attempt('google', 'unknown', 'none', 'failed', 'Missing credential token')
        return jsonify({'success': False, 'message': 'Missing credential token'}), 400
    
    try:
        email = None
        name = None
        picture = None
        
        # Check if running in production mode
        is_production = os.environ.get('ENV') == 'production' or not app.debug
        
        try:
            from google.oauth2 import id_token
            from google.auth.transport import requests as google_requests
            idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), GOOGLE_CLIENT_ID)
            email = idinfo.get('email')
            name = idinfo.get('name')
            picture = idinfo.get('picture')
        except Exception as verr:
            if is_production:
                # Disable JWT decoding fallback completely in production
                raise verr
                
            # Fallback/simulation decoding JWT without signature verification (useful for developer sandbox testing)
            parts = token.split('.')
            if len(parts) == 3:
                payload_b64 = parts[1]
                payload_b64 += '=' * (-len(payload_b64) % 4)
                payload_json = base64.urlsafe_b64decode(payload_b64).decode('utf-8')
                idinfo = json.loads(payload_json)
                email = idinfo.get('email')
                name = idinfo.get('name')
                picture = idinfo.get('picture')
                print(f"WARNING: Google Token signature verification failed or bypassed: {verr}. Extracted email: {email}")
            else:
                log_login_attempt('google', 'unknown', 'invalid-jwt-format', 'failed', f'Invalid token format: {verr}')
                return jsonify({'success': False, 'message': f'Invalid token format: {verr}'}), 400
        
        if not email:
            log_login_attempt('google', 'unknown', 'no-email-in-token', 'failed', 'Email not found in Google token')
            return jsonify({'success': False, 'message': 'Email not found in Google account'}), 400
            
        if staff_collection is None:
            log_login_attempt('google', 'staff', email, 'failed', 'Database not connected')
            return jsonify({'success': False, 'message': 'Database not connected'}), 503
            
        # Match only the email ID against the registered staff database (case-insensitive)
        staff = staff_collection.find_one({'email': {'$regex': f'^{re.escape(email.strip())}$', '$options': 'i'}})
        
        if staff:
            session['logged_in'] = True
            session['user_type'] = 'staff'
            session['username'] = staff['username']
            session['staff_id'] = str(staff['_id'])
            session['user_id'] = str(staff['_id'])
            session['staff_name'] = staff['fullName']
            session['profile_photo'] = picture
            
            log_login_attempt('google', 'staff', email, 'success', f'Welcome {staff["fullName"]}')
            return jsonify({
                'success': True,
                'user_type': 'staff',
                'message': f'Welcome {staff["fullName"]}'
            })
        else:
            log_login_attempt('google', 'unauthorized_staff', email, 'failed', 'Access Denied – Unauthorized Staff Account')
            return jsonify({
                'success': False,
                'message': 'Access Denied – Unauthorized Staff Account'
            }), 403
            
    except Exception as e:
        log_login_attempt('google', 'unknown', 'verification-error', 'failed', f'Authentication failed: {str(e)}')
        print(f"Google authentication error: {e}")
        return jsonify({'success': False, 'message': f'Authentication failed: {str(e)}'}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if username == 'admin' and password == 'admin@123':
        session['logged_in'] = True
        session['user_type'] = 'admin'
        session['username'] = username
        session['user_id'] = 'admin'
        log_login_attempt('manual', 'admin', username, 'success', 'Admin login successful')
        return jsonify({'success': True, 'user_type': 'admin', 'message': 'Admin login successful'})
        
    log_login_attempt('manual', 'unknown', username, 'failed', 'Access Denied – Admin Portal Only')
    return jsonify({'success': False, 'message': 'Access Denied – Admin Portal Only'}), 401

@app.route('/api/admin_impersonate', methods=['POST'])
def admin_impersonate():
    if not session.get('logged_in') or session.get('user_type') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if staff_collection is None:
        return jsonify({'error': 'Database not connected'}), 503
    
    staff = staff_collection.find_one({'username': username, 'password': password})
    if staff:
        session['logged_in'] = True
        session['user_type'] = 'staff'
        session['username'] = staff['username']
        session['staff_id'] = str(staff['_id'])
        session['user_id'] = str(staff['_id'])
        session['staff_name'] = staff['fullName']
        session['profile_photo'] = None # Impersonation has no Google photo
        session['impersonated_by'] = session.get('username', 'admin')
        return jsonify({'success': True, 'message': f'Impersonating {staff["fullName"]}'})
    
    return jsonify({'success': False, 'message': 'Invalid staff credentials'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/check_auth', methods=['GET'])
def check_auth():
    if session.get('logged_in'):
        user_type = session.get('user_type')
        res_data = {
            'authenticated': True, 
            'user_type': user_type,
            'username': session.get('username'),
            'staff_name': session.get('staff_name'),
            'profile_photo': session.get('profile_photo')
        }
        if user_type == 'staff' and staff_collection is not None:
            staff_id = session.get('staff_id')
            if staff_id:
                try:
                    staff = staff_collection.find_one({'_id': ObjectId(staff_id)})
                    if staff:
                        res_data['startTime'] = staff.get('startTime', '10:00')
                        res_data['endTime'] = staff.get('endTime', '20:00')
                except Exception as e:

                    print(f"Error loading staff details in check_auth: {e}")
        return jsonify(res_data)
    return jsonify({'authenticated': False}), 401

# ==================================================
# MAIN ROUTES
# ==================================================

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login_page'))
    
    if session.get('user_type') == 'admin':
        return render_template('admin_dashboard.html')
    else:
        return render_template('staff_attendance.html')

# ==================================================
# STAFF MANAGEMENT (ADMIN ONLY)
# ==================================================

@app.route('/api/staff', methods=['GET', 'POST'])
def manage_staff():
    if staff_collection is None:
        return jsonify({'error': 'Database not connected'}), 503

    if not session.get('logged_in') or session.get('user_type') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    if request.method == 'POST':
        data = request.json
        full_name = data.get('fullName', '').strip()
        class_name = data.get('className', '').strip()
        branch = data.get('branch', '').strip()
        phone = data.get('phone', '').strip()
        email = data.get('email', '').strip()
        
        existing = staff_collection.find_one({'phone': phone})
        if existing:
            return jsonify({'error': 'Phone number already exists'}), 400
        
        username = generate_username(full_name)
        existing_username = staff_collection.find_one({'username': username})
        suffix = 1
        original_username = username
        while existing_username:
            username = f"{original_username}_{suffix}"
            existing_username = staff_collection.find_one({'username': username})
            suffix += 1
        
        password = generate_password(full_name)
        
        new_staff = {
            'staffId': str(uuid.uuid4())[:8],
            'fullName': full_name,
            'className': class_name,
            'branch': branch,
            'phone': phone,
            'email': email,
            'startTime': data.get('startTime', '10:00').strip(),
            'endTime': data.get('endTime', '20:00').strip(),
            'username': username,
            'password': password,
            'createdAt': datetime.now(),
            'students': []
        }
        
        result = staff_collection.insert_one(new_staff)
        
        # Ensure collection index is initialized
        get_students_collection(new_staff['staffId'])
        
        # Invalidate stats cache
        invalidate_stats_cache()
        
        return jsonify({
            'message': 'Staff added successfully',
            'staff': serialize_doc(new_staff),
            'username': username,
            'password': password
        }), 201
    
    all_staff = list(staff_collection.find())
    return jsonify([serialize_doc(staff) for staff in all_staff])

@app.route('/api/staff/<staff_id>', methods=['PUT', 'DELETE'])
def staff_actions(staff_id):
    if staff_collection is None:
        return jsonify({'error': 'Database not connected'}), 503

    if not session.get('logged_in') or session.get('user_type') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    if request.method == 'PUT':
        data = request.json
        full_name = data.get('fullName', '').strip()
        class_name = data.get('className', '').strip()
        branch = data.get('branch', '').strip()
        phone = data.get('phone', '').strip()
        email = data.get('email', '').strip()
        start_time = data.get('startTime', '10:00').strip()
        end_time = data.get('endTime', '20:00').strip()
        
        if not full_name:
            return jsonify({'error': 'Full name is required'}), 400
            
        existing = staff_collection.find_one({'phone': phone, 'staffId': {'$ne': staff_id}})
        if existing:
            return jsonify({'error': 'Phone number already exists for another staff member'}), 400
            
        staff_collection.update_one(
            {'staffId': staff_id},
            {'$set': {
                'fullName': full_name,
                'className': class_name,
                'branch': branch,
                'phone': phone,
                'email': email,
                'startTime': start_time,
                'endTime': end_time
            }}
        )
        invalidate_stats_cache(staff_id)
        return jsonify({'message': 'Staff updated successfully'})
        
    if request.method == 'DELETE':
        staff = staff_collection.find_one({'staffId': staff_id})
        if staff:
            collection_name = f"staff_students_{staff_id}"
            initialized_student_collections.discard(collection_name)
            db.drop_collection(collection_name)
            
            db['staff_self_attendance'].delete_many({'staffId': str(staff['_id'])})
            
            staff_collection.delete_one({'staffId': staff_id})
            invalidate_stats_cache(staff_id)
            return jsonify({'message': 'Staff deleted successfully'})
        
        return jsonify({'error': 'Staff not found'}), 404

# ==================================================
# STUDENT MANAGEMENT (per staff) - FIXED DUPLICATE ISSUE
# ==================================================

@app.route('/api/students', methods=['GET', 'POST'])
def manage_students():
    if db is None or staff_collection is None:
        return jsonify({'error': 'Database not connected'}), 503

    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_id = session.get('staff_id')
    user_type = session.get('user_type')
    
    # Determine the collection name for this staff
    if user_type == 'admin':
        data = request.json if request.method == 'POST' else {}
        target_staff_id = data.get('staffId') if request.method == 'POST' else None
        if not target_staff_id and request.method == 'POST':
            return jsonify({'error': 'Staff ID required'}), 400
        if target_staff_id:
            staff = staff_collection.find_one({'staffId': target_staff_id})
            if not staff:
                return jsonify({'error': 'Staff not found'}), 404
            collection_name = f"staff_students_{target_staff_id}"
        else:
            collection_name = f"staff_students_{staff_id}"
    else:
        collection_name = f"staff_students_{staff_id}"
    
    # Get or create the collection
    students_col = get_students_collection(collection_name[len("staff_students_"):])
    
    if request.method == 'POST':
        data = request.json
        
        # Check if student with same phone already exists for this staff
        existing_student = students_col.find_one({'phone': data.get('phone', '')})
        if existing_student:
            return jsonify({'error': 'A student with this phone number already exists!'}), 400
        
        # Create new student object
        student = {
            'id': str(uuid.uuid4())[:8],
            'name': data.get('name', ''),
            'class': data.get('class', ''),
            'branch': data.get('branch', ''),
            'phone': data.get('phone', ''),
            'parentPhone': data.get('parentPhone', ''),
            'parentName': data.get('parentName', ''),
            'address': data.get('address', ''),
            'days': data.get('days', []),
            'totalClassDays': data.get('totalClassDays', 30),
            'classStartTime': data.get('inTime', '09:00'),
            'classEndTime': data.get('outTime', '17:00'),
            'feeAmount': data.get('feeAmount', 2500),
            'minAttendanceLimit': data.get('minAttendanceLimit', 75),
            'feePaidForMonth': data.get('feePaidForMonth', None),
            'lastFeePaidDate': data.get('lastFeePaidDate', None),
            'isEnded': False,
            'endedDate': None,
            'endedReason': None,
            'timetable': data.get('timetable', []),
            'createdAt': datetime.now()
        }
        
        # Insert into staff's student collection only (NOT into global students collection)
        students_col.insert_one(student)
        
        # Update staff's student list reference
        if user_type == 'staff':
            staff_collection.update_one(
                {'_id': ObjectId(staff_id)},
                {'$push': {'students': student['id']}}
            )
        
        # Invalidate stats cache
        invalidate_stats_cache(target_staff_id if user_type == 'admin' and target_staff_id else staff_id)
        
        return jsonify({'message': 'Student added successfully', 'student': serialize_doc(student)}), 201
    
    # GET - Fetch all active students for this staff (excluding ended ones)
    all_students = list(students_col.find({'isEnded': {'$ne': True}}))
    for student in all_students:
        if 'days' not in student or student['days'] is None:
            student['days'] = []
        if 'isEnded' not in student:
            student['isEnded'] = False
    return jsonify([serialize_doc(s) for s in all_students])

# End Student API
@app.route('/api/students/<student_id>/end', methods=['POST'])
def end_student(student_id):
    if db is None or staff_collection is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in') or session.get('user_type') != 'staff':
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_id = session.get('staff_id')
    data = request.json
    reason = data.get('reason', 'Course Completed')
    
    students_col = get_students_collection(staff_id)
    ended_students_col = db['ended_students']
    
    # Find the student
    student = students_col.find_one({'id': student_id})
    if not student:
        return jsonify({'error': 'Student not found'}), 404
    
    # Add ended information
    student['isEnded'] = True
    student['endedDate'] = datetime.now()
    student['endedReason'] = reason
    student['endedBy'] = session.get('staff_name')
    student['staffId'] = staff_id
    
    # Move to ended students collection
    ended_students_col.insert_one(student)
    
    # Remove from active students collection
    students_col.delete_one({'id': student_id})
    
    # Remove from staff's student list
    staff_collection.update_one(
        {'_id': ObjectId(staff_id)},
        {'$pull': {'students': student_id}}
    )
    
    # Invalidate stats cache
    invalidate_stats_cache(staff_id)
    
    return jsonify({'message': 'Student ended successfully', 'student': serialize_doc(student)})

# Get ended students for staff
@app.route('/api/ended_students', methods=['GET'])
def get_ended_students():
    if db is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in') or session.get('user_type') != 'staff':
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_id = session.get('staff_id')
    ended_students_col = db['ended_students']
    
    ended_students = list(ended_students_col.find({'staffId': staff_id}).sort('endedDate', -1))
    for student in ended_students:
        if 'days' not in student or student['days'] is None:
            student['days'] = []
    
    return jsonify([serialize_doc(s) for s in ended_students])

# Restore ended student
@app.route('/api/ended_students/<student_id>/restore', methods=['POST'])
def restore_student(student_id):
    if db is None or staff_collection is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in') or session.get('user_type') != 'staff':
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_id = session.get('staff_id')
    collection_name = f"staff_students_{staff_id}"
    ended_students_col = db['ended_students']
    
    # Find the ended student
    student = ended_students_col.find_one({'id': student_id, 'staffId': staff_id})
    if not student:
        return jsonify({'error': 'Student not found in ended list'}), 404
    
    # Remove ended flags
    student.pop('isEnded', None)
    student.pop('endedDate', None)
    student.pop('endedReason', None)
    student.pop('endedBy', None)
    
    # Add back to active students
    students_col = get_students_collection(staff_id)
    students_col.insert_one(student)
    
    # Remove from ended collection
    ended_students_col.delete_one({'id': student_id})
    
    # Add back to staff's student list
    staff_collection.update_one(
        {'_id': ObjectId(staff_id)},
        {'$push': {'students': student_id}}
    )
    
    # Invalidate stats cache
    invalidate_stats_cache(staff_id)
    
    return jsonify({'message': 'Student restored successfully'})

@app.route('/api/students/<student_id>', methods=['PUT', 'DELETE'])
def student_actions(student_id):
    if db is None or staff_collection is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_id = session.get('staff_id')
    user_type = session.get('user_type')
    
    if request.method == 'PUT':
        data = request.json
        target_staff_id = data.get('staffId') if user_type == 'admin' else staff_id
        if not target_staff_id:
            return jsonify({'error': 'Staff ID required'}), 400
        collection_name = f"staff_students_{target_staff_id}"
    else:
        target_staff_id = request.args.get('staffId') if user_type == 'admin' else staff_id
        if not target_staff_id:
            return jsonify({'error': 'Staff ID required'}), 400
        collection_name = f"staff_students_{target_staff_id}"
    
    students_col = get_students_collection(target_staff_id)
    
    if request.method == 'PUT':
        data = request.json
        update_data = {k: v for k, v in data.items() if v is not None and k != 'id'}
        students_col.update_one({'id': student_id}, {'$set': update_data})
        invalidate_stats_cache(target_staff_id)
        return jsonify({'message': 'Student updated'})
    
    if request.method == 'DELETE':
        # Since staffId in attendance is the actual staff owner's id, we use target_staff_id
        attendance_collection.delete_many({'studentId': student_id, 'staffId': target_staff_id})
        students_col.delete_one({'id': student_id})
        
        if user_type == 'staff':
            staff_collection.update_one(
                {'_id': ObjectId(staff_id)},
                {'$pull': {'students': student_id}}
            )
        
        invalidate_stats_cache(target_staff_id)
        return jsonify({'message': 'Student deleted'})

# ==================================================
# ATTENDANCE MANAGEMENT
# ==================================================

@app.route('/api/attendance', methods=['GET', 'POST', 'DELETE'])
def manage_attendance():
    if attendance_collection is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_id = session.get('staff_id')
    staff_name = session.get('staff_name')
    
    if request.method == 'POST':
        data = request.json
        records = data.get('attendance', [])
        date = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        operations = []
        saved_records = []
        for record in records:
            status = record.get('status', 'Present')
            if status not in ['Present', 'Absent', 'No Class']:
                continue
            rec_date = record.get('date') or date
            
            query = {
                'studentId': record.get('studentId'),
                'date': rec_date,
                'staffId': staff_id
            }
            if record.get('startTime'):
                query['startTime'] = record.get('startTime')
            if record.get('endTime'):
                query['endTime'] = record.get('endTime')
                
            new_id = str(uuid.uuid4())[:8]
            saved_records.append(new_id)
            
            set_on_insert = {
                'id': new_id,
                'studentId': record.get('studentId'),
                'date': rec_date,
                'staffId': staff_id,
                'createdAt': datetime.now()
            }
            if record.get('startTime'):
                set_on_insert['startTime'] = record.get('startTime')
            if record.get('endTime'):
                set_on_insert['endTime'] = record.get('endTime')
                
            set_fields = {
                'studentName': record.get('studentName'),
                'class': record.get('class', ''),
                'branch': record.get('branch', ''),
                'staffName': staff_name,
                'status': record.get('status', 'Present'),
                'inTime': record.get('inTime', '09:00'),
                'outTime': record.get('outTime', '17:00'),
                'subject': record.get('subject'),
                'remarks': record.get('remarks', ''),
                'reason': record.get('reason', ''),
                'type': record.get('type', '')
            }
            
            operations.append(UpdateOne(
                query,
                {
                    '$setOnInsert': set_on_insert,
                    '$set': set_fields
                },
                upsert=True
            ))
            
        if operations:
            attendance_collection.bulk_write(operations)
            
        invalidate_stats_cache(staff_id)
        return jsonify({'message': 'Attendance saved', 'records': saved_records}), 201
    
    if request.method == 'GET':
        date = request.args.get('date')
        query = {'staffId': staff_id}
        if date:
            query['date'] = date
        
        records = list(attendance_collection.find(query).sort('date', -1))
        return jsonify([serialize_doc(r) for r in records])
    
    if request.method == 'DELETE':
        record_id = request.args.get('id')
        if not record_id:
            return jsonify({'error': 'Record ID required'}), 400
        
        attendance_collection.delete_one({'id': record_id, 'staffId': staff_id})
        invalidate_stats_cache(staff_id)
        return jsonify({'message': 'Attendance deleted'})

def parse_time_to_minutes(time_str):
    try:
        parts = time_str.split(':')
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return 0

@app.route('/api/attendance/no-class', methods=['POST'])
def save_no_class():
    if db is None or attendance_collection is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    staff_id = session.get('staff_id')
    staff_name = session.get('staff_name')
    
    data = request.json
    date = data.get('date')
    event_type = data.get('type') # 'full' or 'partial'
    reason = data.get('reason')
    class_filter = data.get('class', 'All Classes')
    
    if not date or not event_type or not reason:
        return jsonify({'error': 'Missing required fields'}), 400
        
    start_time = data.get('startTime')
    end_time = data.get('endTime')
    
    if event_type == 'partial':
        if not start_time or not end_time:
            return jsonify({'error': 'Start and end time required for partial interruption'}), 400
        if parse_time_to_minutes(start_time) >= parse_time_to_minutes(end_time):
            return jsonify({'error': 'Invalid time range: end time must be greater than start time'}), 400
            
    # Load all active students for this staff
    students_col = get_students_collection(staff_id)
    query = {'isEnded': {'$ne': True}}
    if class_filter != 'All Classes':
        query['class'] = class_filter
        
    active_students = list(students_col.find(query))
    if not active_students:
        return jsonify({'error': 'No student roster found'}), 404
    
    affected_students = []
    previous_states = []
    saved_records = []
    
    for student in active_students:
        # Load period-wise timetable
        timetable = student.get('timetable')
        if not timetable:
            # Fallback to single slot
            timetable = [{
                'startTime': student.get('classStartTime', '09:00'),
                'endTime': student.get('classEndTime', '17:00'),
                'subject': student.get('class', 'Class')
            }]
            
        student_affected_slots = []
        
        for slot in timetable:
            slot_start = slot.get('startTime', '09:00')
            slot_end = slot.get('endTime', '17:00')
            slot_subject = slot.get('subject', 'Class')
            
            is_affected = False
            if event_type == 'full':
                is_affected = True
            elif event_type == 'partial':
                s_min = parse_time_to_minutes(slot_start)
                e_min = parse_time_to_minutes(slot_end)
                ev_s_min = parse_time_to_minutes(start_time)
                ev_e_min = parse_time_to_minutes(end_time)
                
                is_affected = (s_min < ev_e_min) and (e_min > ev_s_min)
                
            if is_affected:
                student_affected_slots.append(slot)
                
                # Fetch existing record for this slot/date/student to store in audit log (conflict resolution)
                existing_query = {
                    'studentId': student['id'],
                    'date': date,
                    'staffId': staff_id,
                    'startTime': slot_start,
                    'endTime': slot_end
                }
                existing = attendance_collection.find_one(existing_query)
                
                prev_state = {
                    'studentId': student['id'],
                    'startTime': slot_start,
                    'endTime': slot_end,
                    'status': None
                }
                if existing:
                    prev_state['status'] = existing.get('status')
                    prev_state['inTime'] = existing.get('inTime')
                    prev_state['outTime'] = existing.get('outTime')
                    prev_state['remarks'] = existing.get('remarks')
                previous_states.append(prev_state)
                
                # Save/Update record to "No Class"
                attendance_record = {
                    'id': str(uuid.uuid4())[:8],
                    'studentId': student['id'],
                    'studentName': student['name'],
                    'class': student.get('class', ''),
                    'branch': student.get('branch', ''),
                    'staffId': staff_id,
                    'staffName': staff_name,
                    'status': 'No Class',
                    'date': date,
                    'inTime': slot_start,
                    'outTime': slot_end,
                    'startTime': slot_start,
                    'endTime': slot_end,
                    'subject': slot_subject,
                    'type': event_type,
                    'reason': reason,
                    'remarks': f"No Class ({reason})",
                    'createdAt': datetime.now()
                }
                
                if existing:
                    # preserve UUID id
                    attendance_record['id'] = existing['id']
                    attendance_collection.update_one(
                        {'_id': existing['_id']},
                        {'$set': attendance_record}
                    )
                else:
                    attendance_collection.insert_one(attendance_record)
                    
                saved_records.append(attendance_record['id'])
                
        if student_affected_slots:
            affected_students.append(student['name'])
            
    # Write Audit Log
    if affected_students:
        audit_log = {
            'staffId': staff_id,
            'staffName': staff_name,
            'actionDate': date,
            'type': event_type,
            'startTime': start_time if event_type == 'partial' else None,
            'endTime': end_time if event_type == 'partial' else None,
            'reason': reason,
            'targetClass': class_filter,
            'affectedStudentsCount': len(affected_students),
            'affectedStudents': affected_students,
            'previousStates': previous_states,
            'undone': False,
            'timestamp': datetime.now()
        }
        db['no_class_audit_logs'].insert_one(audit_log)
    # Invalidate stats cache
    invalidate_stats_cache(staff_id)
    
    return jsonify({
        'message': 'No Class attendance saved successfully',
        'recordsCount': len(saved_records),
        'affectedStudentsCount': len(affected_students)
    }), 200

@app.route('/api/attendance/no-class/undo', methods=['POST'])
def undo_no_class():
    if db is None or attendance_collection is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    staff_id = session.get('staff_id')
    
    # Find the latest audit log entry for this staff that is not already undone
    latest_log = db['no_class_audit_logs'].find_one(
        {'staffId': staff_id, 'undone': {'$ne': True}},
        sort=[('timestamp', -1)]
    )
    
    if not latest_log:
        return jsonify({'error': 'No recent No Class action to undo'}), 404
        
    date = latest_log.get('actionDate')
    previous_states = latest_log.get('previousStates', [])
    
    reverted_count = 0
    deleted_count = 0
    
    for state in previous_states:
        student_id = state.get('studentId')
        start_time = state.get('startTime')
        end_time = state.get('endTime')
        prev_status = state.get('status')
        
        query = {
            'studentId': student_id,
            'date': date,
            'staffId': staff_id,
            'startTime': start_time,
            'endTime': end_time
        }
        
        if prev_status is None:
            # Revert newly created record -> delete it
            attendance_collection.delete_one(query)
            deleted_count += 1
        else:
            # Revert overwritten record -> restore it
            attendance_collection.update_one(
                query,
                {'$set': {
                    'status': prev_status,
                    'inTime': state.get('inTime', '09:00'),
                    'outTime': state.get('outTime', '17:00'),
                    'remarks': state.get('remarks', '')
                }, '$unset': {
                    'type': "",
                    'reason': ""
                }}
            )
            reverted_count += 1
            
    # Mark the audit log as undone
    db['no_class_audit_logs'].update_one(
        {'_id': latest_log['_id']},
        {'$set': {'undone': True}}
    )
    # Invalidate stats cache
    invalidate_stats_cache(staff_id)
    
    return jsonify({
        'message': 'Last No Class action undone successfully',
        'revertedCount': reverted_count,
        'deletedCount': deleted_count
    }), 200

@app.route('/api/no-class-audit-logs', methods=['GET'])
def get_no_class_audit_logs():
    if db is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    staff_id = session.get('staff_id')
    user_type = session.get('user_type')
    
    query = {}
    if user_type != 'admin':
        query['staffId'] = staff_id
        
    logs = list(db['no_class_audit_logs'].find(query).sort('timestamp', -1))
    return jsonify([serialize_doc(l) for l in logs])

@app.route('/api/attendance/<record_id>', methods=['DELETE'])
def delete_attendance_record(record_id):
    if db is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_id = session.get('staff_id')
    
    # 1. Try to delete from attendance
    result = attendance_collection.delete_one({'id': record_id, 'staffId': staff_id})
    if result.deleted_count > 0:
        invalidate_stats_cache(staff_id)
        return jsonify({'message': 'Attendance record deleted'})
        
    # 2. Try to soft-delete in custom_class_slots
    custom_col = db['custom_class_slots']
    custom_slot = custom_col.find_one({'id': record_id})
    if custom_slot:
        custom_col.update_one(
            {'_id': custom_slot['_id']},
            {'$set': {
                'isDeleted': True,
                'deletedAt': datetime.now()
            }}
        )
        invalidate_stats_cache(staff_id)
        return jsonify({'message': 'Custom class slot soft deleted'})
        
    return jsonify({'error': 'Record not found'}), 404

@app.route('/api/custom-class-slots', methods=['GET', 'POST'])
def manage_custom_class_slots():
    if db is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    staff_id = session.get('staff_id')
    custom_col = db['custom_class_slots']
    
    if request.method == 'GET':
        # Load active students for this staff
        students_col = get_students_collection(staff_id)
        active_students = list(students_col.find({'isEnded': {'$ne': True}}))
        active_student_ids = [s['id'] for s in active_students]
        
        slots = list(custom_col.find({
            'studentId': {'$in': active_student_ids},
            'isDeleted': {'$ne': True}
        }))
        return jsonify([serialize_doc(s) for s in slots])
        
    if request.method == 'POST':
        data = request.json
        student_id = data.get('studentId')
        date = data.get('date')
        start_time = data.get('startTime')
        end_time = data.get('endTime')
        subject = data.get('subject')
        
        if not student_id or not date or not start_time or not end_time:
            return jsonify({'error': 'Missing required fields'}), 400
            
        # Load student
        students_col = get_students_collection(staff_id)
        student = students_col.find_one({'id': student_id})
        if not student:
            return jsonify({'error': 'Student not found'}), 404
            
        # Overlap validation: regular timetable slots
        try:
            target_dt = datetime.strptime(date, '%Y-%m-%d')
            weekday = target_dt.strftime('%A')
        except Exception as e:
            return jsonify({'error': 'Invalid date format'}), 400
            
        if weekday in student.get('days', []):
            timetable = student.get('timetable') or []
            if not timetable:
                timetable = [{
                    'startTime': student.get('classStartTime') or student.get('inTime') or '09:00',
                    'endTime': student.get('classEndTime') or student.get('outTime') or '17:00'
                }]
            for slot in timetable:
                slot_start = slot.get('startTime')
                slot_end = slot.get('endTime')
                if start_time < slot_end and end_time > slot_start:
                    return jsonify({'error': 'This student already has a class during this time.'}), 400
                    
        # Overlap validation: other custom class slots
        existing_custom = list(custom_col.find({
            'studentId': student_id,
            'date': date,
            'isDeleted': {'$ne': True}
        }))
        for slot in existing_custom:
            slot_start = slot.get('startTime')
            slot_end = slot.get('endTime')
            if start_time < slot_end and end_time > slot_start:
                return jsonify({'error': 'This student already has a class during this time.'}), 400
                
        # Insert custom class slot
        new_slot = {
            'id': str(uuid.uuid4())[:8],
            'studentId': student_id,
            'date': date,
            'startTime': start_time,
            'endTime': end_time,
            'subject': subject or student.get('class') or 'Class',
            'status': 'Upcoming Class',
            'isDeleted': False,
            'createdAt': datetime.now(),
            'createdBy': staff_id
        }
        custom_col.insert_one(new_slot)
        invalidate_stats_cache(staff_id)
        return jsonify({'message': 'Custom class slot saved successfully', 'slot': serialize_doc(new_slot)}), 201

# ==================================================
# STATISTICS
# ==================================================

@app.route('/api/stats', methods=['GET'])
def get_stats():
    if db is None or staff_collection is None or attendance_collection is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_id = session.get('staff_id')
    user_type = session.get('user_type')
    
    if user_type == 'admin':
        def compute_admin_stats():
            total_staff = staff_collection.count_documents({}) if staff_collection else 0
            
            global_total_students = 0
            global_total_ended = 0
            global_total_pending_fees = 0
            global_fee_completed_count = 0
            
            all_staff = list(staff_collection.find())
            for s in all_staff:
                s_id = s.get('staffId')
                if s_id:
                    students_col = get_students_collection(s_id)
                    try:
                        active = list(students_col.find({'isEnded': {'$ne': True}}))
                        global_total_students += len(active)
                        for stud in active:
                            fee_amount = stud.get('feeAmount', 0)
                            fee_paid = stud.get('feePaidAmount', 0)
                            remaining = fee_amount - fee_paid
                            if remaining > 0:
                                global_total_pending_fees += remaining
                            else:
                                global_fee_completed_count += 1
                    except Exception:
                        pass
            
            global_total_ended = db['ended_students'].count_documents({})
            
            today = datetime.now().strftime('%Y-%m-%d')
            today_records = attendance_collection.count_documents({'date': today})
            present_today = attendance_collection.count_documents({'date': today, 'status': 'Present'})
            
            return {
                'totalStaff': total_staff,
                'totalStudents': global_total_students,
                'totalEnded': global_total_ended,
                'todayTotal': today_records,
                'todayPresent': present_today,
                'totalPendingFees': global_total_pending_fees,
                'feeCompletedCount': global_fee_completed_count,
                'user_type': 'admin'
            }
            
        data = get_cached_stats('admin', compute_admin_stats)
        return jsonify(data)
        
    else:
        def compute_staff_stats():
            students_col = get_students_collection(staff_id)
            active_students = list(students_col.find({'isEnded': {'$ne': True}}))
            total_students = len(active_students)
            
            total_pending_fees = 0
            fee_completed_count = 0
            for stud in active_students:
                fee_amount = stud.get('feeAmount', 0)
                fee_paid = stud.get('feePaidAmount', 0)
                remaining = fee_amount - fee_paid
                if remaining > 0:
                    total_pending_fees += remaining
                else:
                    fee_completed_count += 1
                    
            ended_students_col = db['ended_students']
            total_ended = ended_students_col.count_documents({'staffId': staff_id})
            
            today = datetime.now().strftime('%Y-%m-%d')
            today_records = attendance_collection.count_documents({'staffId': staff_id, 'date': today})
            present_today = attendance_collection.count_documents({'staffId': staff_id, 'date': today, 'status': 'Present'})
            
            return {
                'totalStudents': total_students,
                'totalEnded': total_ended,
                'todayTotal': today_records,
                'todayPresent': present_today,
                'totalPendingFees': total_pending_fees,
                'feeCompletedCount': fee_completed_count,
                'user_type': 'staff'
            }
            
        data = get_cached_stats(staff_id, compute_staff_stats)
        return jsonify(data)

# ==================================================
# ADMIN STUDENTS BY SUBJECT
# ==================================================

@app.route('/api/admin/students_by_subject', methods=['GET'])
def get_students_by_subject():
    if db is None or staff_collection is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in') or session.get('user_type') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Build a lookup map: staffId -> fullName from current staff accounts
        all_staff = list(staff_collection.find())
        staff_name_map = {s.get('staffId'): s.get('fullName', 'Unknown Staff') for s in all_staff}
        
        subject_map = {}
        all_cols = db.list_collection_names()
        
        # Scan ALL staff_students_* collections regardless of whether staff account exists
        for col_name in all_cols:
            if not col_name.startswith('staff_students_'):
                continue
            
            # Extract staffId from collection name
            staff_id = col_name[len('staff_students_'):]
            if not staff_id or staff_id == 'None':
                continue
            
            # Get staff name — use account name if known, otherwise mark as Former Staff
            staff_name = staff_name_map.get(staff_id, f'Former Staff ({staff_id[:8]})')
            
            # Get all non-ended students from this collection
            students = list(db[col_name].find({'isEnded': {'$ne': True}}))
            
            for stud in students:
                stud_serialized = serialize_doc(stud)
                stud_serialized['staffName'] = staff_name
                stud_serialized['staffId'] = staff_id
                
                student_subjects = set()
                
                # 1. Use student's class field
                s_class = (stud.get('class') or '').strip()
                if s_class:
                    student_subjects.add(s_class.title())
                    
                # 2. Use subjects from timetable slots
                timetable = stud.get('timetable') or []
                for slot in timetable:
                    s_subj = (slot.get('subject') or '').strip()
                    if s_subj:
                        student_subjects.add(s_subj.title())
                        
                # Fallback: use 'General' if no subject found
                if not student_subjects:
                    student_subjects.add('General')
                    
                for sub in student_subjects:
                    if sub not in subject_map:
                        subject_map[sub] = []
                    # Avoid duplicates by student id
                    stud_id = stud_serialized.get('id') or str(stud_serialized.get('_id', ''))
                    if not any((x.get('id') or '') == stud_id for x in subject_map[sub]):
                        subject_map[sub].append(stud_serialized)
                        
        return jsonify(subject_map)
    except Exception as e:
        print(f"Error in get_students_by_subject: {e}")
        return jsonify({'error': str(e)}), 500

# ==================================================
# STAFF SELF ATTENDANCE ENDPOINTS
# ==================================================

@app.route('/api/staff_self_attendance', methods=['GET', 'POST'])
def staff_self_attendance_route():
    if db is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in') or session.get('user_type') != 'staff':
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_self_attendance_collection = db['staff_self_attendance']
    staff_id = session.get('staff_id') or session.get('user_id')
    staff_name = session.get('staff_name', 'Staff')

    if request.method == 'POST':
        data = request.json
        in_time = data.get('inTime', '09:00')
        out_time = data.get('outTime', '17:00')
        status = data.get('status', 'Present')
        remarks = data.get('remarks', '')
        target_date = data.get('date') or datetime.now().strftime('%Y-%m-%d')

        existing = staff_self_attendance_collection.find_one({
            'staffId': staff_id,
            'date': target_date
        })
        
        if existing:
            staff_self_attendance_collection.update_one(
                {'_id': existing['_id']},
                {'$set': {
                    'inTime': in_time,
                    'outTime': out_time,
                    'status': status,
                    'remarks': remarks,
                    'timestamp': datetime.utcnow(),
                    'updatedAt': datetime.now()
                }}
            )
            return jsonify({'success': True, 'message': f'Attendance updated to {status}!'}), 200
        else:
            record = {
                'staffId': staff_id,
                'staffName': staff_name,
                'date': target_date,
                'inTime': in_time,
                'outTime': out_time,
                'status': status,
                'remarks': remarks,
                'timestamp': datetime.utcnow(),
                'createdAt': datetime.now()
            }
            
            result = staff_self_attendance_collection.insert_one(record)
            record['_id'] = str(result.inserted_id)
            
            return jsonify({'success': True, 'message': f'{status} attendance logged successfully!', 'record': serialize_doc(record)}), 201

    elif request.method == 'GET':
        logs = list(staff_self_attendance_collection.find({'staffId': staff_id}).sort('date', -1))
        for log in logs:
            log['id'] = str(log['_id'])
            del log['_id']
            if 'timestamp' in log:
                log['timestamp'] = log['timestamp'].isoformat() if log['timestamp'] else None
            if 'createdAt' in log:
                log['createdAt'] = log['createdAt'].isoformat() if log['createdAt'] else None
        
        return jsonify(logs)

@app.route('/api/staff_self_attendance/<log_id>', methods=['DELETE'])
def delete_staff_self_attendance_route(log_id):
    if db is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_self_attendance_collection = db['staff_self_attendance']
    staff_id = session.get('staff_id') or session.get('user_id')
    
    try:
        query = {'_id': ObjectId(log_id)}
        if session.get('user_type') != 'admin':
            query['staffId'] = staff_id

        result = staff_self_attendance_collection.delete_one(query)
        if result.deleted_count > 0:
            return jsonify({'success': True, 'message': 'Log deleted!'})
        return jsonify({'error': 'Record not found or unauthorized'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/admin/all_staff_attendance', methods=['GET'])
def admin_all_staff_attendance():
    if db is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in') or session.get('user_type') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
        
    staff_self_attendance_collection = db['staff_self_attendance']
    logs = list(staff_self_attendance_collection.find().sort('date', -1))
    
    for log in logs:
        log['id'] = str(log['_id'])
        del log['_id']
        if 'timestamp' in log:
            log['timestamp'] = log['timestamp'].isoformat() if log['timestamp'] else None
        if 'createdAt' in log:
            log['createdAt'] = log['createdAt'].isoformat() if log['createdAt'] else None
            
    return jsonify(logs)

# ==================================================
# PWA SUPPORT ENDPOINTS
# ==================================================

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('templates', 'manifest.json', mimetype='application/json')

@app.route('/service-worker.js')
def serve_service_worker():
    return send_from_directory('templates', 'service-worker.js', mimetype='application/javascript')

@app.route('/logo.png')
def serve_logo():
    return send_from_directory('templates', 'download-removebg-preview.png', mimetype='image/png')



# ==================================================
# DOWNLOAD APP ENDPOINT
# ==================================================

@app.route('/download/app')
def download_app():
    import os
    if not os.path.exists(os.path.join('dist', 'Aurora V.75.exe')):
        return jsonify({'error': 'Application build not found on server'}), 404
    return send_from_directory('dist', 'Aurora V.75.exe', as_attachment=True)

# ==================================================
# ATTENDANCE CALENDAR ENDPOINT
# ==================================================

@app.route('/api/calendar-attendance', methods=['GET'])
def get_calendar_attendance():
    if db is None or attendance_collection is None:
        return jsonify({'error': 'Database not connected'}), 503
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff_id = session.get('staff_id')
    user_type = session.get('user_type')
    
    # Allow fetching calendar attendance for a specific staff in admin mode if needed
    target_staff_id = request.args.get('staffId') if user_type == 'admin' else None
    if not target_staff_id:
        target_staff_id = staff_id
        
    if not target_staff_id:
        return jsonify({'error': 'Staff ID required'}), 400

    # Get start and end date from query parameters
    start_date_str = request.args.get('start')
    end_date_str = request.args.get('end')
    
    # Fallback to defaults (e.g. +/- 30 days around today)
    today = datetime.now()
    if not start_date_str:
        start_date_str = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    if not end_date_str:
        end_date_str = (today + timedelta(days=30)).strftime('%Y-%m-%d')
        
    # Standardize start/end date formats to YYYY-MM-DD
    try:
        if 'T' in start_date_str:
            start_date_str = start_date_str.split('T')[0]
        if 'T' in end_date_str:
            end_date_str = end_date_str.split('T')[0]
            
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    except Exception as e:
        return jsonify({'error': f'Invalid date format: {str(e)}'}), 400

    # Load all attendance records for this staff in the date range
    attendance_query = {
        'staffId': target_staff_id,
        'date': {'$gte': start_date_str, '$lte': end_date_str}
    }
    db_records = list(attendance_collection.find(attendance_query))
    
    # We will build a lookup map of actual logged attendance
    # key: (studentId, date, startTime, endTime) -> record
    logged_map = {}
    for r in db_records:
        s_time = r.get('startTime') or r.get('inTime') or '09:00'
        e_time = r.get('endTime') or r.get('outTime') or '17:00'
        # ensure format is HH:MM
        if len(s_time) > 5: s_time = s_time[:5]
        if len(e_time) > 5: e_time = e_time[:5]
        
        key = (r['studentId'], r['date'], s_time, e_time)
        logged_map[key] = r

    # Load active students for this staff
    collection_name = f"staff_students_{target_staff_id}"
    print(f"CALENDAR-ATTENDANCE: Fetching events for staff {target_staff_id} in range {start_date_str} to {end_date_str}")
    students_col = db[collection_name]
    try:
        active_students = list(students_col.find({'isEnded': {'$ne': True}}))
        print(f"CALENDAR-ATTENDANCE: Found {len(active_students)} active students in roster '{collection_name}'")
    except Exception as err:
        print(f"CALENDAR-ATTENDANCE: Error querying student collection '{collection_name}': {err}")
        active_students = []

    # Load custom class slots for these active students
    active_student_ids = [s['id'] for s in active_students]
    custom_slots_col = db['custom_class_slots']
    custom_slots = list(custom_slots_col.find({
        'studentId': {'$in': active_student_ids},
        'date': {'$gte': start_date_str, '$lte': end_date_str},
        'isDeleted': {'$ne': True}
    }))
    
    # Group custom slots by date
    custom_slots_by_date = {}
    for cs in custom_slots:
        custom_slots_by_date.setdefault(cs['date'], []).append(cs)

    calendar_events = []
    today_str = today.strftime('%Y-%m-%d')
    
    # Loop through each date in the range
    curr_date = start_date
    while curr_date <= end_date:
        curr_date_str = curr_date.strftime('%Y-%m-%d')
        weekday = curr_date.strftime('%A')
        
        # Check active students who have classes on this weekday
        for student in active_students:
            student_days = student.get('days', [])
            if weekday not in student_days:
                continue
                
            timetable = student.get('timetable') or []
            if not timetable:
                timetable = [{
                    'startTime': student.get('classStartTime') or student.get('inTime') or '09:00',
                    'endTime': student.get('classEndTime') or student.get('outTime') or '17:00',
                    'subject': student.get('class') or 'Class'
                }]
                
            for slot in timetable:
                s_time = slot.get('startTime', '09:00')
                e_time = slot.get('endTime', '17:00')
                subject = slot.get('subject', 'Class')
                
                if len(s_time) > 5: s_time = s_time[:5]
                if len(e_time) > 5: e_time = e_time[:5]
                
                key = (student['id'], curr_date_str, s_time, e_time)
                
                if key in logged_map:
                    record = logged_map[key]
                    status = record.get('status', 'Present')
                    subj = record.get('subject') or subject
                    calendar_events.append({
                        'id': record.get('id') or f"{student['id']}_{curr_date_str}_{s_time}",
                        'studentId': student['id'],
                        'studentName': student['name'],
                        'date': curr_date_str,
                        'startTime': s_time,
                        'endTime': e_time,
                        'status': status,
                        'class': student.get('class', ''),
                        'subject': subj,
                        'remarks': record.get('remarks', ''),
                        'staffName': record.get('staffName', ''),
                        'title': f"{student['name']} ({subj})",
                        'extendedProps': {
                            'studentName': student['name'],
                            'studentId': student['id'],
                            'date': curr_date_str,
                            'startTime': s_time,
                            'endTime': e_time,
                            'status': status,
                            'class': student.get('class', ''),
                            'subject': subj,
                            'remarks': record.get('remarks', ''),
                            'staffName': record.get('staffName', '')
                        }
                    })
                    logged_map.pop(key)
                else:
                    # No attendance record exists. Check if date is after student's creation date
                    created_at = student.get('createdAt')
                    should_append = True
                    if created_at:
                        if isinstance(created_at, datetime):
                            created_date_str = created_at.strftime('%Y-%m-%d')
                        else:
                            created_date_str = str(created_at)[:10]
                        if curr_date_str < created_date_str:
                            should_append = False
                    
                    if should_append:
                        calendar_events.append({
                            'id': f"upcoming_{student['id']}_{curr_date_str}_{s_time}",
                            'studentId': student['id'],
                            'studentName': student['name'],
                            'date': curr_date_str,
                            'startTime': s_time,
                            'endTime': e_time,
                            'status': 'Upcoming Class',
                            'class': student.get('class', ''),
                            'subject': subject,
                            'remarks': 'Upcoming Scheduled Class' if curr_date_str >= today_str else 'Unmarked Scheduled Class',
                            'staffName': '',
                            'title': f"{student['name']} ({subject})",
                            'extendedProps': {
                                'studentName': student['name'],
                                'studentId': student['id'],
                                'date': curr_date_str,
                                'startTime': s_time,
                                'endTime': e_time,
                                'status': 'Upcoming Class',
                                'class': student.get('class', ''),
                                'subject': subject,
                                'remarks': 'Upcoming Scheduled Class' if curr_date_str >= today_str else 'Unmarked Scheduled Class',
                                'staffName': ''
                            }
                        })
        # Check custom class slots for this date
        today_custom = custom_slots_by_date.get(curr_date_str, [])
        for cs in today_custom:
            student = next((s for s in active_students if s['id'] == cs['studentId']), None)
            if not student:
                continue
                
            s_time = cs['startTime']
            e_time = cs['endTime']
            if len(s_time) > 5: s_time = s_time[:5]
            if len(e_time) > 5: e_time = e_time[:5]
            
            key = (cs['studentId'], curr_date_str, s_time, e_time)
            
            if key in logged_map:
                record = logged_map[key]
                status = record.get('status', 'Present')
                subj = record.get('subject') or cs.get('subject') or 'Class'
                calendar_events.append({
                    'id': record.get('id') or f"{cs['studentId']}_{curr_date_str}_{s_time}",
                    'studentId': cs['studentId'],
                    'studentName': student['name'],
                    'date': curr_date_str,
                    'startTime': s_time,
                    'endTime': e_time,
                    'status': status,
                    'class': student.get('class', ''),
                    'subject': subj,
                    'remarks': record.get('remarks', ''),
                    'staffName': record.get('staffName', ''),
                    'title': f"{student['name']} ({subj})",
                    'extendedProps': {
                        'studentName': student['name'],
                        'studentId': cs['studentId'],
                        'date': curr_date_str,
                        'startTime': s_time,
                        'endTime': e_time,
                        'status': status,
                        'class': student.get('class', ''),
                        'subject': subj,
                        'remarks': record.get('remarks', ''),
                        'staffName': record.get('staffName', '')
                    }
                })
                logged_map.pop(key, None)
            else:
                calendar_events.append({
                    'id': cs['id'],
                    'studentId': cs['studentId'],
                    'studentName': student['name'],
                    'date': curr_date_str,
                    'startTime': s_time,
                    'endTime': e_time,
                    'status': 'Upcoming Class',
                    'class': student.get('class', ''),
                    'subject': cs.get('subject') or 'Class',
                    'remarks': 'Upcoming Scheduled Custom Class',
                    'staffName': '',
                    'title': f"{student['name']} ({cs.get('subject') or 'Class'})",
                    'extendedProps': {
                        'studentName': student['name'],
                        'studentId': cs['studentId'],
                        'date': curr_date_str,
                        'startTime': s_time,
                        'endTime': e_time,
                        'status': 'Upcoming Class',
                        'class': student.get('class', ''),
                        'subject': cs.get('subject') or 'Class',
                        'remarks': 'Upcoming Scheduled Custom Class',
                        'staffName': ''
                    }
                })
                        
        curr_date += timedelta(days=1)
        
    # Any remaining records in logged_map (e.g. historical records of deleted/ended students)
    for (student_id, date_str, s_time, e_time), record in logged_map.items():
        student_name = record.get('studentName', 'Unknown Student')
        subj = record.get('subject', 'Class')
        status = record.get('status', 'Present')
        calendar_events.append({
            'id': record.get('id') or f"{student_id}_{date_str}_{s_time}",
            'studentId': student_id,
            'studentName': student_name,
            'date': date_str,
            'startTime': s_time,
            'endTime': e_time,
            'status': status,
            'class': record.get('class', ''),
            'subject': subj,
            'remarks': record.get('remarks', ''),
            'staffName': record.get('staffName', ''),
            'title': f"{student_name} ({subj})",
            'extendedProps': {
                'studentName': student_name,
                'studentId': student_id,
                'date': date_str,
                'startTime': s_time,
                'endTime': e_time,
                'status': status,
                'class': record.get('class', ''),
                'subject': subj,
                'remarks': record.get('remarks', ''),
                'staffName': record.get('staffName', '')
            }
        })

    print(f"CALENDAR-ATTENDANCE: Successfully compiled and returning {len(calendar_events)} events.")
    return jsonify(calendar_events)

# ==================================================
# HEALTH CHECK
# ==================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    global client, db
    if client is None or db is None:
        init_db()
    if client is None:
        print("Health check: client is None")
        return jsonify({'status': 'disconnected', 'mongodb': False}), 500
    try:
        client.admin.command('ping')
        return jsonify({'status': 'connected', 'mongodb': True})
    except Exception as e:
        print(f"Health check ping failed: {e}")
        # Try to reconnect once
        init_db()
        if client is not None:
            try:
                client.admin.command('ping')
                return jsonify({'status': 'connected', 'mongodb': True})
            except:
                pass
        return jsonify({'status': 'disconnected', 'mongodb': False}), 500

if __name__ == '__main__':
    print("\n" + "="*60)
    print("Starting Staff Management System...")
    print("="*60)
    print("\nLogin Credentials:")
    print("   Admin Login:")
    print("   Username: admin")
    print("   Password: admin@123")
    print("\nServer running at:")
    print("   http://localhost:5000")
    print("="*60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
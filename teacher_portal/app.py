from flask import Flask, render_template,request,redirect,session, url_for,send_file,jsonify,send_from_directory,current_app, flash
import requests

import psycopg2.extras

import psycopg2
import psycopg2.extras

from weasyprint import HTML
import io
import os
from werkzeug.security import generate_password_hash, check_password_hash

from datetime import datetime
if not os.getenv("RENDER"):
 from dotenv import load_dotenv
 load_dotenv()

import os
app= Flask(__name__)
app.secret_key='tafara victor'
ADMIN_SIGNUP_SECRET = "NEO-CLASS-2025"

#database  connection function
def get_database():
    host = os.getenv('DB_HOST', '').strip()
    user = os.getenv('DB_USER', '').strip()
    password = os.getenv('DB_PASSWORD', '').strip()
    database = os.getenv('DB_NAME', '').strip()
    port = os.getenv('DB_PORT', '5432').strip()

    if not all([host, user, password, database]):
        raise Exception("One or more environment variables are missing!")

    return psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=database,
        cursor_factory=psycopg2.extras.DictCursor
    )
def log_activity_to_db(user_id, user_type, activity_type, description, status='Success'):
    """Insert an activity log entry with user ID, type, description, etc."""
    try:
        conn = get_database()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO activity_logs (timestamp, user_id, user_type, activity_type, description, status, ip_address)
            VALUES (NOW(), %s, %s, %s, %s, %s, %s)
        """, (user_id, user_type, activity_type, description, status, request.remote_addr))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"⚠️ Failed to log activity: {e}")
        
def is_teacher_portal_locked():
    """Return True if the teacher portal is locked."""
    try:
        conn = get_database()
        cursor = conn.cursor()
        cursor.execute("SELECT is_locked FROM portal_status WHERE portal = 'teacher'")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        locked = row[0] if row else True
        print(f"🔒 is_teacher_portal_locked() = {locked}")   # ← must be here
        return locked
    except Exception as e:
        print(f"❌ Error in is_teacher_portal_locked: {e}")
        return True
# ============================
# TEACHER LOGIN
# ============================
# ============================
# TEACHER LOGIN (SECURE HASH VERSION)
# ============================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Fetch teacher by username only (no password in query)
        cursor.execute("SELECT * FROM teachers WHERE username = %s", (username,))
        teacher = cursor.fetchone()
        cursor.close()
        conn.close()

        if teacher:
            # Verify the entered password against the stored hash
            if check_password_hash(teacher['password'], password):
                session['teacher'] = teacher['username']
                session['teacher_id'] = teacher['id']
                
                # Log teacher login
                log_activity_to_db(
                    user_id=teacher['username'],
                    user_type='teacher',
                    activity_type='teacher_login',
                    description=f"Teacher {teacher['username']} logged in",
                    status='Success'
                )
                
                print(f"✅ Teacher {teacher['username']} logged in successfully")
                return redirect('/select_class')
            else:
                # Password incorrect
                print(f"❌ Invalid password for username: {username}")
                return render_template('login.html', error="Invalid credentials.")
        else:
            # Username not found
            print(f"❌ Invalid login attempt for username: {username}")
            return render_template('login.html', error="Invalid credentials.")
    
    return render_template('login.html')

# ============================
# SELECT CLASS & SUBJECT
# ============================
@app.route('/select_class', methods=['GET', 'POST'])
def select_class():
    """Teacher selects class, subject, and term"""
    if 'teacher' not in session:
        return redirect('/')

    # 🔒 NEW: Portal lock check
    if is_teacher_portal_locked():
        from flask import flash
        flash("⚠️ The teacher mark entry portal is currently locked. Please contact the administrator.", "error")
        # Render the page with the flash message instead of redirecting to avoid loop
        return render_template('select_class.html', 
                             classes=[], 
                             subjects=[], 
                             terms=['Term 1', 'Term 2', 'Term 3'])

    teacher_username = session['teacher']
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get teacher ID
        cursor.execute("SELECT id FROM teachers WHERE username = %s", (teacher_username,))
        teacher = cursor.fetchone()
        
        if not teacher:
            cursor.close()
            conn.close()
            return "Teacher not found", 404
        
        teacher_id = teacher['id']
        
        print(f"📌 Teacher ID: {teacher_id}")

        if request.method == 'POST':
            class_id = request.form.get('class_id')
            subject_id = request.form.get('subject_id')
            term = request.form.get('term')

            print(f"📝 Form submitted: class_id={class_id}, subject_id={subject_id}, term={term}")

            # ✅ Validate teacher assignment
            cursor.execute("""
                SELECT id FROM subject_teacher
                WHERE teacher_id = %s AND class_id = %s AND subject_id = %s
            """, (teacher_id, class_id, subject_id))
            
            assignment = cursor.fetchone()
            cursor.close()
            conn.close()

            if not assignment:
                print(f"❌ Teacher {teacher_username} (ID: {teacher_id}) not assigned to class {class_id}, subject {subject_id}")
                from flask import flash
                flash("❌ You are not assigned to teach this subject for the selected class. Please contact the administrator.", "error")
                return redirect(url_for('select_class'))

            print(f"✅ Assignment validated. Redirecting to enter_marks")
            return redirect(url_for('enter_marks', class_id=class_id, subject_id=subject_id, term=term))

        # GET – fetch assigned classes
        cursor.execute("""
            SELECT DISTINCT st.class_id, c.id, c.name
            FROM subject_teacher st
            JOIN classes c ON st.class_id = c.id
            WHERE st.teacher_id = %s
            ORDER BY c.name ASC
        """, (teacher_id,))
        classes = cursor.fetchall()
        
        print(f"🔍 Query result for classes: {[(c['id'], c['name']) for c in classes]}")

        # GET – fetch assigned subjects
        cursor.execute("""
            SELECT DISTINCT st.subject_id, s.id, s.name, st.class_id
            FROM subject_teacher st
            JOIN subjects s ON st.subject_id = s.id
            WHERE st.teacher_id = %s
            ORDER BY s.name ASC
        """, (teacher_id,))
        subjects = cursor.fetchall()
        
        print(f"🔍 Query result for subjects: {[(s['id'], s['name'], s['class_id']) for s in subjects]}")

        cursor.close()
        conn.close()

        print(f"✅ Loaded {len(classes)} classes and {len(subjects)} subjects for teacher {teacher_username}")

        if not classes:
            from flask import flash
            flash("⚠️ You have not been assigned to any classes yet. Please contact the administrator.", "warning")

        return render_template('select_class.html', 
                             classes=classes, 
                             subjects=subjects, 
                             terms=['Term 1', 'Term 2', 'Term 3'])

    except Exception as e:
        print(f"❌ Error in select_class: {e}")
        import traceback
        traceback.print_exc()
        from flask import flash
        flash(f"An error occurred: {str(e)}", "error")
        return redirect('/')
# ============================
# ENTER MARKS (GET & POST)
# ============================
@app.route('/enter_marks', methods=['GET', 'POST'])
def enter_marks():
    """Teacher enters marks for students"""
    if 'teacher' not in session:
        return redirect('/')

    # 🔒 Portal lock check
    if is_teacher_portal_locked():
        from flask import flash
        flash("⚠️ The teacher mark entry portal is currently locked. Please contact the administrator.", "error")
        return redirect(url_for('select_class'))

    teacher_username = session['teacher']
    errors = {}

    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get teacher ID
        cursor.execute("SELECT id FROM teachers WHERE username = %s", (teacher_username,))
        teacher = cursor.fetchone()
        
        if not teacher:
            cursor.close()
            conn.close()
            return "Teacher not found", 404
        
        teacher_id = teacher['id']

        if request.method == 'POST':
            class_id = request.form.get('class_id')
            subject_id = request.form.get('subject_id')
            term = request.form.get('term')
            mode = request.form.get('mode', 'add')

            print(f"📝 Saving marks: class={class_id}, subject={subject_id}, term={term}, mode={mode}")

            # ✅ Re-validate assignment on POST (security)
            cursor.execute("""
                SELECT id FROM subject_teacher
                WHERE teacher_id = %s AND class_id = %s AND subject_id = %s
            """, (teacher_id, class_id, subject_id))
            
            if not cursor.fetchone():
                cursor.close()
                conn.close()
                from flask import flash
                flash("❌ You are not authorized to enter marks for this class and subject.", "error")
                return redirect(url_for('select_class'))

            # Process each student's marks
            for key in request.form:
                if key.startswith('mark_'):
                    student_id = key.split('_')[1]
                    score = request.form.get(key, '').strip()
                    comment = request.form.get(f'comment_{student_id}', '').strip()

                    if not score:
                        continue  # Skip empty marks

                    try:
                        score_num = float(score)
                        if score_num < 0 or score_num > 100:
                            errors[student_id] = "Mark must be between 0 and 100"
                            continue
                    except ValueError:
                        errors[student_id] = "Mark must be a number"
                        continue

                    # Check if mark exists
                    cursor.execute("""
                        SELECT id FROM marks
                        WHERE student_id = %s AND subject_id = %s AND term = %s
                    """, (student_id, subject_id, term))
                    
                    existing = cursor.fetchone()

                    if existing:
                        if mode == 'edit':
                            # ✅ FIXED: removed updated_at
                            cursor.execute("""
                                UPDATE marks 
                                SET score = %s, comment = %s
                                WHERE id = %s
                            """, (score_num, comment, existing['id']))
                            print(f"✏️ Updated mark for student {student_id}")
                        else:
                            errors[student_id] = "Mark already entered for this term"
                    else:
                        # ✅ FIXED: removed created_at, updated_at
                        cursor.execute("""
                            INSERT INTO marks (student_id, subject_id, term, score, comment)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (student_id, subject_id, term, score_num, comment))
                        print(f"✅ Created mark for student {student_id}")

            if errors:
                conn.rollback()
                print(f"❌ Errors found: {errors}")
                cursor.close()
                conn.close()
                from flask import flash
                flash(f"❌ Some marks could not be saved: {errors}", "error")
                return redirect(url_for('enter_marks', class_id=class_id, subject_id=subject_id, term=term))

            conn.commit()

            # ✅ FIXED: use correct function name
            log_activity_to_db(
                user_id=teacher_username,
                user_type='teacher',
                activity_type='mark_entry' if mode == 'add' else 'mark_edit',
                description=f"{'Entered' if mode == 'add' else 'Edited'} marks for class {class_id}, subject {subject_id}, term {term}",
                status='Success'
            )

            print(f"✅ Marks saved successfully")
            cursor.close()
            conn.close()
            
            from flask import flash
            flash(f"✅ Marks saved successfully for {term}!", "success")
            return redirect(url_for('mark_success', subject_id=subject_id, class_id=class_id, term=term))

        else:
            # GET request – show form
            class_id = request.args.get('class_id')
            subject_id = request.args.get('subject_id')
            term = request.args.get('term')

            print(f"📋 Loading form: class_id={class_id}, subject_id={subject_id}, term={term}")

            if not (class_id and subject_id and term):
                cursor.close()
                conn.close()
                return redirect('/select_class')

            # ✅ Validate assignment on GET (prevent direct URL access)
            cursor.execute("""
                SELECT id FROM subject_teacher
                WHERE teacher_id = %s AND class_id = %s AND subject_id = %s
            """, (teacher_id, class_id, subject_id))
            
            if not cursor.fetchone():
                cursor.close()
                conn.close()
                from flask import flash
                flash("❌ You are not assigned to this class/subject.", "error")
                return redirect(url_for('select_class'))

            # Fetch students
            cursor.execute("""
                SELECT s.id, s.firstname, s.surname
                FROM students s
                WHERE s.class_id = %s
                ORDER BY s.firstname, s.surname
            """, (class_id,))
            students = cursor.fetchall()

            # Fetch existing marks
            cursor.execute("""
                SELECT student_id, score, comment
                FROM marks
                WHERE subject_id = %s AND term = %s
            """, (subject_id, term))
            
            existing_marks = cursor.fetchall()
            marks_dict = {row['student_id']: {'score': row['score'], 'comment': row['comment']} for row in existing_marks}

            # Fetch class and subject names
            cursor.execute("SELECT name FROM classes WHERE id = %s", (class_id,))
            class_result = cursor.fetchone()
            class_name = class_result['name'] if class_result else 'Unknown Class'

            cursor.execute("SELECT name FROM subjects WHERE id = %s", (subject_id,))
            subject_result = cursor.fetchone()
            subject_name = subject_result['name'] if subject_result else 'Unknown Subject'

            cursor.close()
            conn.close()

            mode = 'edit' if marks_dict else 'add'
            
            print(f"✅ Loaded {len(students)} students with {len(marks_dict)} existing marks")

            return render_template('enter_marks.html',
                                 students=students,
                                 marks=marks_dict,
                                 class_id=class_id,
                                 subject_id=subject_id,
                                 class_name=class_name,
                                 subject_name=subject_name,
                                 term=term,
                                 mode=mode,
                                 errors=errors)

    except Exception as e:
        print(f"❌ Error in enter_marks: {e}")
        from flask import flash
        flash(f"An error occurred: {str(e)}", "error")
        return redirect('/select_class')

# ============================
# GET COMMENT SUGGESTION API
# ============================
@app.route('/api/suggest-comment')
def suggest_comment():
    """Suggests a comment based on the mark score"""
    try:
        score = float(request.args.get('score', 0))
    except ValueError:
        return jsonify({'comment': '', 'grade': '-'}), 400

    comment = get_comment_suggestion(score)
    grade = get_grade_from_score(score)
    
    return jsonify({
        'score': score,
        'comment': comment,
        'grade': grade
    })


def get_comment_suggestion(score):
    """Generate a comment based on score"""
    if score >= 90:
        return "Excellent work! Outstanding performance."
    elif score >= 80:
        return "Very good performance. Well done!"
    elif score >= 70:
        return "Good understanding shown. Well done!"
    elif score >= 60:
        return "Satisfactory work. Good effort."
    elif score >= 50:
        return "Acceptable work. Needs improvement."
    elif score >= 40:
        return "Needs improvement. Seek additional support."
    else:
        return "Requires immediate intervention and support."


def get_grade_from_score(score):
    """Convert score to grade"""
    if score >= 90:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B+"
    elif score >= 60:
        return "B"
    elif score >= 50:
        return "C"
    elif score >= 40:
        return "D"
    else:
        return "F"


# ============================
# DEBUG ENDPOINT
# ============================
@app.route('/api/debug/teacher-data')
def debug_teacher_data():
    """Debug endpoint to check teacher data"""
    if 'teacher' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        teacher_username = session['teacher']
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Get teacher info
        cursor.execute("SELECT id, username FROM teachers WHERE username = %s", (teacher_username,))
        teacher = cursor.fetchone()
        
        # Get assigned classes
        cursor.execute("""
            SELECT DISTINCT c.id, c.name
            FROM classes c
            JOIN subject_teacher st ON st.class_id = c.id
            WHERE st.teacher_id = %s
        """, (teacher['id'],))
        classes = cursor.fetchall()
        
        # Get assigned subjects
        cursor.execute("""
            SELECT DISTINCT s.id, s.name, st.class_id
            FROM subjects s
            JOIN subject_teacher st ON st.subject_id = s.id
            WHERE st.teacher_id = %s
        """, (teacher['id'],))
        subjects = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'teacher': dict(teacher),
            'classes': [dict(c) for c in classes],
            'subjects': [dict(s) for s in subjects],
            'total_classes': len(classes),
            'total_subjects': len(subjects)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


#returning back to the  login page
@app.route('/marks_success/<int:subject_id>/<int:class_id>/<term>')
def mark_success(subject_id,class_id,term):
     conn=get_database()
     cursor=conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
     #suject name
     cursor.execute("select name from  subjects  where id =%s ",(subject_id,))
     subject=cursor.fetchone()
     subject_name=subject['name'] if subject else "unknown"
     #class name
     cursor.execute("select name from classes where id=%s",(class_id,))
     classes=cursor.fetchone()
     class_name=classes['name'] if classes else "unknown class"
                    
     
    #total students who do that subject
     cursor.execute("""
    SELECT COUNT(DISTINCT m.student_id)
    FROM marks m
    JOIN students s ON s.id = m.student_id
    WHERE m.subject_id = %s AND s.class_id = %s AND m.term = %s
""", (subject_id, class_id, term))
     total_students=cursor.fetchone()[0]
     # Top performer (based on highest mark)
     cursor.execute("""
        SELECT s.firstname || ' ' || s.surname AS name, MAX(m.score) as max_score
        FROM marks m
        JOIN students s ON s.id = m.student_id
                    where m.subject_id=%s AND s.class_id = %s AND m.term = %s
        GROUP BY s.firstname, s.surname

        ORDER BY  max_score DESC
        LIMIT 1;
                    """,(subject_id,class_id,term))
     top_performer = cursor.fetchone()
     #passrate for the subject
     cursor.execute("""
    SELECT ROUND(
        COUNT(*) FILTER (WHERE m.score >= 50)::numeric 
        / NULLIF(COUNT(*), 0) * 100, 2
    ) AS pass_rate
    FROM marks m
    JOIN students s ON s.id = m.student_id
    WHERE m.subject_id = %s AND s.class_id = %s AND m.term = %s
""", (subject_id, class_id, term))


     pass_rate = cursor.fetchone()['pass_rate']

     #top 5 students
     cursor.execute("""
                    select s.firstname || ' ' || s.surname AS name,m.student_id,m.score 
                    from marks m
                    join students s on s.id=m.student_id
                    where m.subject_id=%s AND s.class_id = %s AND m.term = %s
                    order by m.score desc
                    limit 5
                    """,(subject_id,class_id,term))
     top_5=cursor.fetchall()
     #bottom 5 students
     cursor.execute(""" select s.firstname || ' ' || s.surname AS name,m.student_id,m.score
                    from marks m
                    join students s on s.id=m.student_id
                    where m.subject_id=%s AND s.class_id = %s AND m.term = %s
                    order by m.score asc
                    limit 5
""",(subject_id,class_id,term))
     bottom_5=cursor.fetchall()





     #donout code
     cursor.execute("""
     SELECT
        COUNT(*) FILTER (WHERE m.score >= 50) AS passed,
        COUNT(*) FILTER (WHERE m.score < 50) AS failed
     FROM marks m
     JOIN students s ON s.id = m.student_id
     WHERE m.subject_id = %s
      AND s.class_id = %s
      AND m.term = %s
     """, (subject_id, class_id, term))

     row = cursor.fetchone()
     passed = row['passed'] or 0
     failed = row['failed'] or 0




 # ANALYTICS FOR STUDENTS
     cursor.execute("""
    SELECT m.score
    FROM marks m
    JOIN students s ON s.id = m.student_id
    WHERE m.subject_id = %s
      AND s.class_id = %s
      AND m.term = %s
     """, (subject_id, class_id, term))

     marks = [row['score'] for row in cursor.fetchall()] or []

     total_student = len(marks)
     overall_passed = sum(1 for m in marks if m >= 50)
     overall_failed = sum(1 for m in marks if m < 50)

     pass_rate = round(
     (overall_passed / total_student) * 100, 2
     ) if total_student else 0

     
     # GRADE DISTRIBUTION
     
     grades = {
    'A': [],
    'B': [],
    'C': [],
    'D': [],
    'E': [],
    'F': []
     }
     for score in marks:
         if score >= 75:
          grades['A'].append(score)
         elif score >= 65:
          grades['B'].append(score)
         elif score >= 50:
          grades['C'].append(score)
         elif score >= 40:
          grades['D'].append(score)
         elif score >= 30:
          grades['E'].append(score)
         else:
          grades['F'].append(score)


# BUILDing ANALYTICS TABLE

     analytics = []

     for symbol, scores in grades.items():
      total = len(scores)
      passed = sum(1 for s in scores if s >= 50)
      failed = sum(1 for s in scores if s < 50)
      mean_mark = round(sum(scores) / total, 2) if total else 0

      analytics.append({
        'symbol': symbol,
        'num_students': total,
        'passed': passed,
        'failed': failed,
        'mean': mean_mark
       })


# OVERALL ANALYTICS

     total_student = sum(a['num_students'] for a in analytics)
     total_passed = sum(a['passed'] for a in analytics)
     total_failed = sum(a['failed'] for a in analytics)

     overall_mean = round(
     sum(marks) / len(marks), 2
     ) if marks else 0


     return render_template(
    'marks_success.html',
    subject_name=subject_name,
    class_name=class_name,
    total_students=total_students,
    total_student=total_student,
    top_5=top_5,
    bottom_5=bottom_5,
    top_performer=top_performer,
    pass_rate=pass_rate,
    analytics=analytics,
    overall_mean=overall_mean,
    total_passed=total_passed,
    total_failed=total_failed,
    passed=passed,
    failed=failed,
    term=term
)



    

#admin button at the teacher login 
@app.route('/button_click')
def admin_entrance():
    return redirect(url_for('/admin_login'))
# ------------------- ADMIN SIGN-UP -------------------
@app.route('/admin_signup', methods=['POST'])
def admin_signup():
    """Register a new admin – hashes password, verifies security code, redirects to login."""
    conn = get_database()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Get form data
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    firstname = request.form.get('firstname', '').strip()
    surname = request.form.get('surname', '').strip()
    security_code = request.form.get('security_code', '').strip()

    # Validation
    if not all([username, password, firstname, surname, security_code]):
        conn.close()
        return "All fields are required.", 400

    if security_code != ADMIN_SIGNUP_SECRET:
        conn.close()
        return "Invalid system security code.", 403

    # Check if username already exists
    cursor.execute("SELECT id FROM admins WHERE username = %s", (username,))
    if cursor.fetchone():
        conn.close()
        return "Username already taken. Please choose another.", 409

    # Hash the password before storing
    hashed_password = generate_password_hash(password)

    # Insert new admin
    try:
        cursor.execute("""
            INSERT INTO admins (username, password, firstname, surname)
            VALUES (%s, %s, %s, %s)
        """, (username, hashed_password, firstname, surname))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return f"Database error: {str(e)}", 500

    conn.close()

    # Redirect to login page with success message
    flash('Account created! Please log in.', 'success')
    return redirect(url_for('admin_login'))


# ------------------- UPDATED ADMIN LOGIN (HASHED PASSWORD) -------------------
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    conn = get_database()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        term = request.form['term']

        # Fetch admin by username only (no password in query)
        cursor.execute("SELECT * FROM admins WHERE username = %s", (username,))
        admin = cursor.fetchone()
        conn.close()

        if admin:
            # Verify the entered password against the stored hash
            if check_password_hash(admin['password'], password):
                session['admin'] = admin['username']
                session['admin_id'] = admin['id']
                session['admin_name'] = f"{admin['firstname']} {admin['surname']}"
                session['term'] = term
                return redirect('/admin_dashboard')
            else:
                return "Invalid username or password. Try again."
        else:
            return "Invalid username or password. Try again."

    return render_template('admin_login.html')
 

# ============================
# ADMIN DASHBOARD
# ============================

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin' not in session:
        return redirect('/admin_login')
    
    conn = get_database()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    # Gets term from session
    term = session.get('term')
    admin_name = session.get('admin_name')
    
    cursor.execute("SELECT id, name FROM classes")
    classes = cursor.fetchall()
    
    # Card codes
    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM teachers")
    total_teachers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM classes")
    total_classes = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM subjects")
    total_subjects = cursor.fetchone()[0]

    # Best Classes (average mark)
    cursor.execute("""
        SELECT c.name, ROUND(AVG(m.score),1)
        FROM marks m
        JOIN students s ON m.student_id = s.id
        JOIN classes c ON s.class_id = c.id
        GROUP BY c.name
        ORDER BY AVG(m.score) DESC
        LIMIT 5
    """)
    best_classes = cursor.fetchall()
    
    # Top 4 students per class with number of subjects and average score
    cursor.execute("""
        SELECT *
        FROM (
            SELECT 
                s.firstname || ' ' || s.surname AS name,
                c.name AS class_name,
                m.term,
                COUNT(m.subject_id) AS num_subjects,
                ROUND(AVG(m.score), 2) AS avg_score,
                ROW_NUMBER() OVER (PARTITION BY s.class_id ORDER BY AVG(m.score) DESC) AS rn
            FROM students s
            JOIN classes c ON s.class_id = c.id
            JOIN marks m ON s.id = m.student_id
            WHERE m.term = %s
            GROUP BY s.id, s.firstname, s.surname, c.name, m.term
        ) sub
        WHERE rn <= 3
        ORDER BY avg_score DESC
    """, (term,))

    top_students = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('admin_dashboard.html',
        admin_name=admin_name,
        classes=classes,
        total_students=total_students,
        total_teachers=total_teachers,
        total_classes=total_classes,
        total_subjects=total_subjects,
        best_classes=best_classes,
        top_students=top_students
    )
#api for the graph
@app.route('/api/class-passrates/<int:class_id>')
def class_passrates(class_id):
    if 'admin' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    term = session.get('term')

    conn = get_database()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cursor.execute("""
        SELECT 
            sub.name AS subject,
            COUNT(m.score) AS total,
            SUM(CASE WHEN m.score >= 50 THEN 1 ELSE 0 END) AS passed
        FROM marks m
        JOIN students s ON s.id = m.student_id
        JOIN subjects sub ON sub.id = m.subject_id
        WHERE s.class_id = %s
          AND m.term = %s
        GROUP BY sub.name
        ORDER BY sub.name
    """, (class_id, term))

    results = cursor.fetchall()

    subjects = []
    pass_rates = []

    for row in results:
        rate = round((row["passed"] / row["total"]) * 100, 2) if row["total"] else 0
        subjects.append(row["subject"])
        pass_rates.append(rate)

    return jsonify({
        "subjects": subjects,
        "pass_rates": pass_rates
    })

@app.route('/api/school-performance')
def school_performance():
    if 'admin' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    term = session.get('term')

    conn = get_database()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Fetch all classes
    cursor.execute("SELECT id, name FROM classes")
    classes = cursor.fetchall()

    school_data = []

    for c in classes:
        class_id = c['id']

        # Get pass rates per subject for this class
        cursor.execute("""
            SELECT 
                COUNT(m.score) AS total,
                SUM(CASE WHEN m.score >= 50 THEN 1 ELSE 0 END) AS passed
            FROM marks m
            JOIN students s ON s.id = m.student_id
            WHERE s.class_id = %s AND m.term = %s
            GROUP BY m.subject_id
        """, (class_id, term))

        subject_results = cursor.fetchall()
        pass_rates = []

        for row in subject_results:
            rate = (row['passed'] / row['total'] * 100) if row['total'] else 0
            pass_rates.append(rate)

        class_avg = round(sum(pass_rates)/len(pass_rates),2) if pass_rates else 0
        school_data.append((c['name'], class_avg))

    conn.close()

    return jsonify({
        "schoolLabels": [c[0] for c in school_data],
        "schoolData": [c[1] for c in school_data]
    })


# GENERATION OF REPORTS


# ============================================
# HELPER FUNCTION
# ============================================
def calculate_grade(score):
    """Convert numerical score to grade letter"""
    if score >= 90:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B+"
    elif score >= 60:
        return "B"
    elif score >= 50:
        return "C"
    elif score >= 40:
        return "D"
    else:
        return "F"

# ============================================
# ROUTE: HOME PAGE
# ============================================

@app.route("/")
def index():
    """Home page"""
    return render_template("index.html")

# ============================================
# ROUTE: GET ALL CLASSES
# ============================================

@app.route("/classes", methods=["GET"])
def get_classes():
    """Get all classes for dropdown"""
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("SELECT id, name FROM classes ORDER BY name")
        classes = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "success": True,
            "classes": [dict(c) for c in classes]
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ============================================
# ROUTE: GET ALL TERMS
# ============================================

@app.route("/terms", methods=["GET"])
def get_terms():
    """Get all available terms"""
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("SELECT DISTINCT term FROM marks ORDER BY term DESC")
        terms = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "success": True,
            "terms": [t["term"] for t in terms]
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ============================================
# ROUTE: GENERATE CLASS REPORTS PDF
# ============================================
@app.route("/generate-class-reports", methods=["POST"])
def generate_class_reports():
    """Generate PDF reports for all students in a selected class - ONE PAGE PER STUDENT"""
    try:
        # Get term from session first, then from request
        term = request.json.get("term") or session.get('term')
        class_id = request.json.get("class_id")

        print(f"DEBUG: class_id={class_id}, term={term}")

        if not class_id:
            return jsonify({
                "success": False,
                "message": "Class ID is required"
            }), 400

        if not term:
            return jsonify({
                "success": False,
                "message": "Term is required"
            }), 400

        print(f"Generating reports for class_id={class_id}, term={term}")

        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get class name
        cursor.execute("SELECT name FROM classes WHERE id=%s", (class_id,))
        class_row = cursor.fetchone()
        
        if not class_row:
            conn.close()
            return jsonify({
                "success": False,
                "message": "Class not found"
            }), 404

        class_name = class_row["name"]
        print(f"Found class: {class_name}")

        # Get all students
        cursor.execute("""
            SELECT id, firstname, surname, firstname || ' ' || surname AS fullname
            FROM students
            WHERE class_id=%s
            ORDER BY firstname, surname
        """, (class_id,))
        students = cursor.fetchall()
        print(f"Found {len(students)} students")

        if not students:
            conn.close()
            return jsonify({
                "success": False,
                "message": "No students found in this class"
            }), 404

        # Get logo path
        logo_path = os.path.join(current_app.root_path, "static", "funda.png")
        
        if not os.path.exists(logo_path):
            print(f"Logo not found at {logo_path}")
            logo_html = ""
        else:
            import base64
            with open(logo_path, "rb") as img_file:
                logo_base64 = base64.b64encode(img_file.read()).decode()
            logo_html = f'<img src="data:image/png;base64,{logo_base64}" alt="School Logo" class="school-logo">'
            print("Logo loaded successfully")

        # Define CSS (same as before)
        css_styles = """
        <style>
            @page {
                size: A4;
                margin: 5mm;
            }
            
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            html, body {
                margin: 0;
                padding: 0;
                height: auto;
            }
            
            body {
                font-family: Arial, sans-serif;
                color: #333;
                position: relative;
            }
            
            .watermark {
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%) rotate(-45deg);
                font-size: 80px;
                color: rgba(200, 200, 200, 0.1);
                font-weight: bold;
                text-align: center;
                z-index: -1;
                width: 100%;
                height: 100%;
                pointer-events: none;
                white-space: nowrap;
            }
            
            .report-page {
                width: 100%;
                min-height: 257mm;
                page-break-after: always;
                page-break-inside: avoid;
                display: flex;
                flex-direction: column;
                font-size: 9pt;
                line-height: 1.2;
            }
            
            .report-page:last-child {
                margin-bottom: 0;
                page-break-after: avoid;
            }
            
            .report-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 2px solid #1a3a52;
                padding-bottom: 5mm;
                margin-bottom: 5mm;
            }
            
            .logo-section {
                width: 35mm;
                height: 35mm;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-right: 4mm;
            }
            
            .school-logo {
                max-width: 100%;
                max-height: 100%;
                object-fit: contain;
            }
            
            .school-header {
                flex: 1;
            }
            
            .school-name {
                font-size: 14pt;
                font-weight: bold;
                color: #1a3a52;
                margin-bottom: 2px;
                line-height: 1.1;
            }
            
            .school-info {
                font-size: 7pt;
                color: #555;
                line-height: 1.2;
            }
            
            .school-info-line {
                display: block;
            }
            
            .report-title {
                font-size: 11pt;
                font-weight: bold;
                color: #1a3a52;
                text-align: center;
                flex: 1;
                border-left: 1px solid #ddd;
                border-right: 1px solid #ddd;
                padding: 0 4mm;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            
            .student-details {
                margin-bottom: 4mm;
                background-color: #f5f5f5;
                padding: 4mm;
                border-radius: 2px;
            }
            
            .info-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 8pt;
            }
            
            .info-table tr {
                border: none;
            }
            
            .info-table td {
                padding: 1.5mm 3mm;
            }
            
            .info-label {
                font-weight: bold;
                color: #1a3a52;
                width: 20%;
            }
            
            .info-value {
                color: #333;
                width: 30%;
                border-bottom: 1px solid #ddd;
            }
            
            .performance-section {
                margin-bottom: 4mm;
            }
            
            .section-title {
                font-size: 9pt;
                font-weight: bold;
                color: #1a3a52;
                border-bottom: 1.5px solid #2c5aa0;
                padding-bottom: 2mm;
                margin-bottom: 3mm;
            }
            
            .results-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 8pt;
                margin-bottom: 20mm;
            }
            
            .results-table thead {
                background-color: #2c5aa0;
                color: white;
            }
            
            .results-table th {
                padding: 2mm 2mm;
                text-align: left;
                font-weight: bold;
                border: 0.5px solid #1a3a52;
                font-size: 7.5pt;
            }
            
            .results-table td {
                padding: 2mm;
                border: 0.5px solid #ddd;
                font-size: 8pt;
            }
            
            .results-table tbody tr:nth-child(even) {
                background-color: #f9f9f9;
            }
            
            .col-subject {
                width: 45%;
            }
            
            .col-score {
                width: 12%;
                text-align: center;
            }
            
            .col-grade {
                width: 12%;
                text-align: center;
            }
            
            .col-comment {
                width: 31%;
                font-size: 7pt;
            }
            
            .grade-badge {
                display: inline-block;
                padding: 1mm 2mm;
                border-radius: 2px;
                font-weight: bold;
                color: white;
                font-size: 8pt;
                min-width: 20px;
                text-align: center;
            }
            
            .grade-a-plus, .grade-a {
                background-color: #27ae60;
            }
            
            .grade-b-plus, .grade-b {
                background-color: #3498db;
            }
            
            .grade-c {
                background-color: #f39c12;
            }
            
            .grade-d {
                background-color: #e67e22;
            }
            
            .grade-f {
                background-color: #e74c3c;
            }
            
            .analysis-section {
                margin-bottom: 5mm;
                margin-top:10mm;
            }
            
            .analysis-box {
                display: flex;
                justify-content: space-between;
                background-color: #e8f4f8;
                padding: 3mm;
                border-radius: 2px;
                border-left: 3px solid #2c5aa0;
                gap: 2mm;
            }
            
            .analysis-item {
                display: flex;
                flex-direction: column;
                align-items: center;
                text-align: center;
                flex: 1;
            }
            
            .analysis-label {
                font-size: 7pt;
                color: #1a3a52;
                font-weight: bold;
                margin-bottom: 1mm;
                line-height: 1.1;
            }
            
            .analysis-value {
                font-size: 8.5pt;
                color: #2c5aa0;
                font-weight: bold;
                background-color: white;
                padding: 1.5mm 2mm;
                border-radius: 2px;
                border: 0.5px solid #2c5aa0;
                width: 100%;
            }
            
            .summary-section {
                margin-bottom: 5mm;
            }
            
            .summary-box {
                display: flex;
                justify-content: space-around;
                background-color: #f5f5f5;
                padding: 3mm;
                border-radius: 2px;
                border: 0.5px solid #ddd;
            }
            
            .summary-item {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                text-align: center;
                flex: 1;
            }
            
            .summary-label {
                font-size: 7pt;
                color: #666;
                font-weight: bold;
                margin-bottom: 0.8mm;
            }
            
            .summary-value {
                font-size: 10pt;
                font-weight: bold;
                color: #1a3a52;
            }
            
            .grade-large {
                display: inline-block;
                padding: 2mm 4mm;
                border-radius: 2px;
                color: white;
                font-size: 12pt;
                font-weight: bold;
            }
            
            .remarks-section {
                margin-bottom: 5mm;
            }
            
            .remarks-box {
                background-color: #fafafa;
                border-left: 2px solid #2c5aa0;
                padding: 3mm;
                font-size: 8pt;
                line-height: 1.3;
            }
            
            .remarks-box p {
                margin: 0;
                color: #333;
            }
            
            .footer-section {
                margin-top: auto;
                padding-top: 3mm;
                border-top: 0.5px solid #ddd;
            }
            
            .signature-line {
                display: flex;
                justify-content: space-around;
                margin-bottom: 3mm;
            }
            
            .sig-item {
                display: flex;
                flex-direction: column;
                align-items: center;
                width: 30%;
                text-align: center;
            }
            
            .sig-title {
                font-weight: bold;
                font-size: 8pt;
                color: #1a3a52;
                margin-bottom: 0.8mm;
            }
            
            .sig-space {
                height: 10mm;
                border-bottom: 0.5px solid #333;
                width: 100%;
                margin: 0.8mm 0;
            }
            
            .sig-date {
                font-size: 7pt;
                color: #666;
                margin-top: 0.8mm;
            }
            
            .footer-text {
                text-align: center;
                font-size: 6pt;
                color: #999;
                margin-top: 1mm;
            }
        </style>
        """
        

       

        # Start HTML
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Class Reports - {class_name} - {term}</title>
            {css_styles}
        </head>
        <body>
        <div class="watermark">OFFICIAL DOCUMENT</div>
        """

        # Loop through each student
        for index, student in enumerate(students):
            print(f"Processing student {index + 1}/{len(students)}: {student['fullname']}")
            
            # Get marks for THIS SPECIFIC TERM
            cursor.execute("""
                SELECT 
                    sub.name AS subject,
                    m.score,
                    m.comment
                FROM marks m
                JOIN subjects sub ON sub.id = m.subject_id
                WHERE m.student_id=%s AND m.term=%s
                ORDER BY sub.name
            """, (student["id"], term))
            
            marks = cursor.fetchall()
            print(f"Found {len(marks)} marks for student {student['fullname']}")

            # Calculate
            results = []
            total_score = 0
            passed_count = 0
            
            if marks:
                for mark in marks:
                    score = mark["score"]
                    total_score += score
                    if score >= 40:
                        passed_count += 1

                    results.append({
                        "subject": mark["subject"],
                        "score": score,
                        "grade": calculate_grade(score),
                        "comment": mark["comment"] or ""
                    })

                average = round(total_score / len(results), 2)
                pass_rate = round(passed_count / len(results) * 100, 2)
            else:
                average = 0
                pass_rate = 0
                print(f"WARNING: No marks found for {student['fullname']} in term {term}")

            overall_grade = calculate_grade(average)

            # Calculate Subject Analysis
            if results:
                best_subject = max(results, key=lambda x: x['score'])
                worst_subject = min(results, key=lambda x: x['score'])
                highest_score = max([r['score'] for r in results])
                lowest_score = min([r['score'] for r in results])
            else:
                best_subject = {"subject": "N/A", "score": 0}
                worst_subject = {"subject": "N/A", "score": 0}
                highest_score = 0
                lowest_score = 0

            # Remarks
            if overall_grade in ['A+', 'A']:
                remarks = "Excellent performance! Outstanding academic achievement."
            elif overall_grade in ['B+', 'B']:
                remarks = "Very good performance. Good understanding of subject matter."
            elif overall_grade == 'C':
                remarks = "Satisfactory performance. Needs improvement in some areas."
            elif overall_grade == 'D':
                remarks = "Needs improvement. Additional support is recommended."
            else:
                remarks = "Requires immediate intervention and academic support."

            # Build table rows
            subject_rows = ""
            for result in results:
                grade_class = f"grade-{result['grade'].replace('+', '-plus').lower()}"
                comment = result['comment'][:30] + "..." if len(result['comment']) > 30 else result['comment']
                subject_rows += f"""
                <tr>
                    <td class="col-subject">{result['subject']}</td>
                    <td class="col-score">{result['score']}</td>
                    <td class="col-grade"><span class="grade-badge {grade_class}">{result['grade']}</span></td>
                    <td class="col-comment">{comment}</td>
                </tr>
                """

            overall_grade_class = f"grade-{overall_grade.replace('+', '-plus').lower()}"

            # Build report
            report_html = f"""
            <div class="report-page">
                <div class="report-header">
                    <div class="logo-section">
                        {logo_html}
                    </div>
                    <div class="school-header">
                        <div class="school-name">MUTARE TEACHERS COLLEGE PRACTISING HIGH SCHOOL</div>
                        <div class="school-info">
                            <span class="school-info-line">81 Chimanimani Road</span>
                            <span class="school-info-line">Paulington Mutare</span>
                            <span class="school-info-line">+263 20 60380 |64623 |66672 </span>
                        </div>
                    </div>
                    <div class="report-title">REPORT CARD</div>
                </div>

                <div class="student-details">
                    <table class="info-table">
                        <tr>
                            <td class="info-label">Name:</td>
                            <td class="info-value">{student['fullname']}</td>
                            <td class="info-label">ID:</td>
                            <td class="info-value">{student['id']}</td>
                        </tr>
                        <tr>
                            <td class="info-label">Class:</td>
                            <td class="info-value">{class_name}</td>
                            <td class="info-label">Term:</td>
                            <td class="info-value">{term}</td>
                        </tr>
                    </table>
                </div>

                <div class="performance-section">
                    <h3 class="section-title">Academic Performance</h3>
                    <table class="results-table">
                        <thead>
                            <tr>
                                <th class="col-subject">Subject</th>
                                <th class="col-score">Score</th>
                                <th class="col-grade">Grade</th>
                                <th class="col-comment">Comment</th>
                            </tr>
                        </thead>
                        <tbody>
                            {subject_rows}
                        </tbody>
                    </table>
                </div>

                <div class="analysis-section">
                    <h3 class="section-title">Subject Analysis</h3>
                    <div class="analysis-box">
                        <div class="analysis-item">
                            <span class="analysis-label">Best Subject:</span>
                            <span class="analysis-value">{best_subject['subject']}</span>
                        </div>
                        <div class="analysis-item">
                            <span class="analysis-label">Highest Score:</span>
                            <span class="analysis-value">{highest_score}</span>
                        </div>
                        <div class="analysis-item">
                            <span class="analysis-label">Lowest Score:</span>
                            <span class="analysis-value">{lowest_score}</span>
                        </div>
                        <div class="analysis-item">
                            <span class="analysis-label">Weakest Subject:</span>
                            <span class="analysis-value">{worst_subject['subject']}</span>
                        </div>
                    </div>
                </div>

                <div class="summary-section">
                    <div class="summary-box">
                        <div class="summary-item">
                            <span class="summary-label">Average</span>
                            <span class="summary-value">{average}</span>
                        </div>
                        <div class="summary-item">
                            <span class="summary-label">Grade</span>
                            <span class="summary-value grade-large {overall_grade_class}">{overall_grade}</span>
                        </div>
                        <div class="summary-item">
                            <span class="summary-label">Pass Rate</span>
                            <span class="summary-value">{pass_rate}%</span>
                        </div>
                    </div>
                </div>

                <div class="remarks-section">
                    <h3 class="section-title">Remarks</h3>
                    <div class="remarks-box">
                        <p>{remarks}</p>
                    </div>
                </div>

                <div class="footer-section">
                    <div class="signature-line">
                        <div class="sig-item">
                            <p class="sig-title">HeadMaster</p>
                            <div class="sig-space"></div>
                            <p class="sig-date">Date: _____/_____/_____</p>
                        </div>
                        <div class="sig-item">
                            <p class="sig-title">Principal</p>
                            <div class="sig-space"></div>
                            <p class="sig-date">Date: _____/_____/_____</p>
                        </div>
                        <div class="sig-item">
                            <p class="sig-title">Parent</p>
                            <div class="sig-space"></div>
                            <p class="sig-date">Date: _____/_____/_____</p>
                        </div>
                    </div>
                    <div class="footer-text">
                        <p>Official Document - MUTARE TEACHERS COLLEGE PRACTISING HIGH SCHOOL</p>
                    </div>
                </div>
            </div>
            """

            html_content += report_html

        # Close HTML
        html_content += """
        </body>
        </html>
        """

        conn.close()

        print("Starting PDF generation...")
        
        # Generate PDF
        try:
            html = HTML(string=html_content)
            print("HTML parsed successfully")
            
            pdf_bytes = html.write_pdf()
            print(f"PDF generated successfully, size: {len(pdf_bytes)} bytes")

            # Create folder
            reports_folder = os.path.join(current_app.root_path, "static", "reports")
            os.makedirs(reports_folder, exist_ok=True)
            print(f"Reports folder: {reports_folder}")

            # Save
            filename = f"class_{class_id}_{term.replace(' ', '_')}_{int(datetime.now().timestamp())}.pdf"
            pdf_path = os.path.join(reports_folder, filename)

            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)

            print(f"PDF saved to: {pdf_path}")

            return jsonify({
                "success": True,
                "download": f"/static/reports/{filename}",
                "message": f"Successfully generated {len(students)} report(s) for {term}",
                "students_count": len(students)
            })

        except Exception as e:
            print(f"PDF Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                "success": False,
                "message": f"PDF Generation Error: {str(e)}"
            }), 500

    except Exception as e:
        print(f"Route Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "message": f"Error: {str(e)}"
        }), 500
# ============================================
# CSS STYLES FOR PDF (Embedded)
# ============================================

PDF_STYLES = """
<style>
    /* Page Layout */
    .report-page {
        width: 210mm;
        height: 297mm;
        padding: 15mm 12mm;
        margin: 0;
        background: white;
        page-break-after: always;
        display: flex;
        flex-direction: column;
        font-size: 10pt;
    }

    /* ============================================ */
    /* HEADER STYLES */
    /* ============================================ */
    .report-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 3px solid #1a3a52;
        padding-bottom: 10mm;
        margin-bottom: 10mm;
    }

    .school-header {
        flex: 1;
    }

    .school-name {
        font-size: 18pt;
        font-weight: bold;
        color: #1a3a52;
        margin-bottom: 3px;
    }

    .school-info {
        font-size: 8pt;
        color: #555;
        line-height: 1.3;
    }

    .school-info span {
        display: block;
    }

    .report-title {
        font-size: 14pt;
        font-weight: bold;
        color: #1a3a52;
        text-align: center;
        flex: 1;
        border-left: 1px solid #ddd;
        border-right: 1px solid #ddd;
        padding: 0 10mm;
    }

    /* ============================================ */
    /* STUDENT DETAILS */
    /* ============================================ */
    .student-details {
        margin-bottom: 8mm;
        background-color: #f5f5f5;
        padding: 8mm;
        border-radius: 3px;
    }

    .info-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 9pt;
    }

    .info-table tr {
        border: none;
    }

    .info-table td {
        padding: 3mm 5mm;
    }

    .info-table .label {
        font-weight: bold;
        color: #1a3a52;
        width: 20%;
    }

    .info-table .value {
        color: #333;
        width: 30%;
        border-bottom: 1px solid #ddd;
    }

    /* ============================================ */
    /* PERFORMANCE SECTION */
    /* ============================================ */
    .performance-section {
        margin-bottom: 8mm;
        flex-grow: 1;
    }

    .section-title {
        font-size: 11pt;
        font-weight: bold;
        color: #1a3a52;
        border-bottom: 2px solid #2c5aa0;
        padding-bottom: 3mm;
        margin-bottom: 4mm;
    }

    .results-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 9pt;
        margin-bottom: 8mm;
    }

    .results-table thead {
        background-color: #2c5aa0;
        color: white;
    }

    .results-table th {
        padding: 4mm 3mm;
        text-align: left;
        font-weight: bold;
        border: 1px solid #1a3a52;
    }

    .results-table td {
        padding: 3mm;
        border: 1px solid #ddd;
    }

    .results-table tbody tr:nth-child(even) {
        background-color: #f9f9f9;
    }

    /* Column Widths */
    .col-subject {
        width: 20%;
    }

    .col-code {
        width: 10%;
        text-align: center;
    }

    .col-score {
        width: 12%;
        text-align: center;
    }

    .col-grade {
        width: 12%;
        text-align: center;
    }

    .col-comment {
        width: 46%;
    }

    /* Grade Badges */
    .grade-badge {
        display: inline-block;
        padding: 2mm 4mm;
        border-radius: 3px;
        font-weight: bold;
        color: white;
        font-size: 9pt;
        min-width: 25px;
        text-align: center;
    }

    .grade-a-plus, .grade-a {
        background-color: #27ae60;
    }

    .grade-b-plus, .grade-b {
        background-color: #3498db;
    }

    .grade-c {
        background-color: #f39c12;
    }

    .grade-d {
        background-color: #e67e22;
    }

    .grade-f {
        background-color: #e74c3c;
    }

    /* ============================================ */
    /* SUMMARY SECTION */
    /* ============================================ */
    .summary-section {
        margin-bottom: 8mm;
    }

    .summary-box {
        display: flex;
        justify-content: space-around;
        background-color: #f5f5f5;
        padding: 6mm;
        border-radius: 3px;
        border: 1px solid #ddd;
    }

    .summary-item {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }

    .summary-label {
        font-size: 8pt;
        color: #666;
        font-weight: bold;
        margin-bottom: 2mm;
    }

    .summary-value {
        font-size: 12pt;
        font-weight: bold;
        color: #1a3a52;
    }

    .grade-large {
        display: inline-block;
        padding: 4mm 8mm;
        border-radius: 4px;
        color: white;
        font-size: 14pt;
    }

    /* ============================================ */
    /* REMARKS SECTION */
    /* ============================================ */
    .remarks-section {
        margin-bottom: 6mm;
    }

    .remarks-box {
        background-color: #fafafa;
        border-left: 3px solid #2c5aa0;
        padding: 4mm 5mm;
        border-radius: 2px;
        font-size: 9pt;
        line-height: 1.4;
    }

    .remarks-box p {
        margin: 0;
        color: #333;
    }

    /* ============================================ */
    /* FOOTER SECTION */
    /* ============================================ */
    .footer-section {
        margin-top: auto;
        padding-top: 6mm;
        border-top: 1px solid #ddd;
    }

    .signature-line {
        display: flex;
        justify-content: space-around;
        margin-bottom: 6mm;
    }

    .sig-item {
        display: flex;
        flex-direction: column;
        align-items: center;
        width: 30%;
        text-align: center;
    }

    .sig-title {
        font-weight: bold;
        font-size: 9pt;
        color: #1a3a52;
        margin-bottom: 2mm;
    }

    .sig-space {
        height: 20mm;
        border-bottom: 1px solid #333;
        width: 100%;
        margin-bottom: 2mm;
    }

    .sig-date {
        font-size: 8pt;
        color: #666;
    }

    .footer-text {
        text-align: center;
        font-size: 7pt;
        color: #999;
        margin-top: 2mm;
    }

    /* ============================================ */
    /* PRINT OPTIMIZATION */
    /* ============================================ */
    @media print {
        body {
            margin: 0;
            padding: 0;
        }
        
        .report-page {
            margin: 0;
            box-shadow: none;
            page-break-after: always;
        }
    }
</style>
"""



@app.route('/api/search')
def search():
    """
    Search for students, classes, teachers, and subjects
    Query parameter: ?query=search_term
    """
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    query = request.args.get('query', '').strip()
    
    if len(query) < 2:
        return jsonify({'results': []})
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        results = []
        search_term = f'%{query}%'
        
        # ============================
        # SEARCH STUDENTS
        # ============================
        try:
            cursor.execute("""
                SELECT 
                    id,
                    firstname || ' ' || surname AS name,
                    'student' AS type
                FROM students
                WHERE firstname ILIKE %s 
                   OR surname ILIKE %s 
                   OR (firstname || ' ' || surname) ILIKE %s
                LIMIT 5
            """, (search_term, search_term, search_term))
            
            students = cursor.fetchall()
            for student in students:
                results.append({
                    'id': student['id'],
                    'name': student['name'],
                    'type': 'student'
                })
            print(f"✅ Found {len(students)} students")
        except Exception as e:
            print(f"❌ Student search error: {str(e)}")
        
        # ============================
        # SEARCH CLASSES
        # ============================
        try:
            cursor.execute("""
                SELECT 
                    id,
                    name,
                    'class' AS type
                FROM classes
                WHERE name ILIKE %s
                LIMIT 5
            """, (search_term,))
            
            classes = cursor.fetchall()
            for cls in classes:
                results.append({
                    'id': cls['id'],
                    'name': cls['name'],
                    'type': 'class'
                })
            print(f"✅ Found {len(classes)} classes")
        except Exception as e:
            print(f"❌ Class search error: {str(e)}")
        
        # ============================
        # SEARCH TEACHERS
        # ============================
        try:
            cursor.execute("""
                SELECT 
                    id,
                    username AS name,
                    'teacher' AS type
                FROM teachers
                WHERE username ILIKE %s
                LIMIT 5
            """, (search_term,))
            
            teachers = cursor.fetchall()
            for teacher in teachers:
                results.append({
                    'id': teacher['id'],
                    'name': teacher['name'],
                    'type': 'teacher'
                })
            print(f"✅ Found {len(teachers)} teachers")
        except Exception as e:
            print(f"❌ Teacher search error: {str(e)}")
        
        # ============================
        # SEARCH SUBJECTS
        # ============================
        try:
            cursor.execute("""
                SELECT 
                    id,
                    name,
                    'subject' AS type
                FROM subjects
                WHERE name ILIKE %s
                LIMIT 5
            """, (search_term,))
            
            subjects = cursor.fetchall()
            for subject in subjects:
                results.append({
                    'id': subject['id'],
                    'name': subject['name'],
                    'type': 'subject'
                })
            print(f"✅ Found {len(subjects)} subjects")
        except Exception as e:
            print(f"❌ Subject search error: {str(e)}")
        
        conn.close()
        
        print(f"📊 Total results: {len(results)}")
        return jsonify({'results': results})
    
    except Exception as e:
        print(f"❌ Main search error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Search error: {str(e)}'
        }), 500

# ============================
# TEACHERS MANAGEMENT TAB API ROUTES
# ============================
# ============================
# TEACHERS MANAGEMENT TAB API ROUTES
# ============================

@app.route('/api/get-teachers')
def get_teachers():
    """Fetch all teachers with their pass rates for the selected term"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        term = session.get('term')
        print(f"🟢 get_teachers called, term: {term}")

        # Get all teachers
        cursor.execute("""
            SELECT id, username, email
            FROM teachers
            ORDER BY username
        """)
        teachers = cursor.fetchall()
        print(f"✅ Found {len(teachers)} teachers")

        teachers_data = []

        for teacher in teachers:
            # Get all distinct subjects taught by this teacher
            cursor.execute("""
                SELECT DISTINCT s.id, s.name
                FROM subject_teacher st
                INNER JOIN subjects s ON s.id = st.subject_id
                WHERE st.teacher_id = %s
                ORDER BY s.name
            """, (teacher['id'],))

            subjects = cursor.fetchall()
            subject_names = ', '.join(s['name'] for s in subjects) if subjects else 'No subjects'

            # Calculate pass rate
            pass_rate = 0
            if subjects:
                subject_ids = [s['id'] for s in subjects]
                query = """
                    SELECT AVG(CASE WHEN m.score >= 50 THEN 100 ELSE 0 END) AS pass_rate
                    FROM marks m
                    WHERE m.subject_id = ANY(%s)
                """
                params = [subject_ids]
                
                if term:
                    query += " AND m.term = %s"
                    params.append(term)
                
                cursor.execute(query, params)
                result = cursor.fetchone()
                pass_rate = float(result['pass_rate']) if result and result['pass_rate'] else 0

            teachers_data.append({
                'id': teacher['id'],
                'name': teacher['username'],
                'email': teacher['email'] or f"teacher_{teacher['id']}@school.local",
                'subject': subject_names,
                'phone': 'N/A',
                'pass_rate': round(pass_rate, 1)
            })

        # Get top 3 teachers
        top_teachers = sorted(
            teachers_data,
            key=lambda x: x['pass_rate'],
            reverse=True
        )[:3]

        cursor.close()
        conn.close()

        print(f"✅ Returning {len(teachers_data)} teachers with top {len(top_teachers)} performers")
        
        return jsonify({
            'success': True,
            'teachers': teachers_data,
            'top_teachers': top_teachers,
            'total_count': len(teachers_data)
        })

    except Exception as e:
        print(f"❌ Error fetching teachers: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/get-teacher/<int:teacher_id>')
def get_teacher(teacher_id):
    """Get detailed information about a specific teacher"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get teacher basic info
        cursor.execute("""
            SELECT id, username, email
            FROM teachers
            WHERE id = %s
        """, (teacher_id,))
        
        teacher = cursor.fetchone()
        
        if not teacher:
            print(f"❌ Teacher {teacher_id} not found")
            cursor.close()
            conn.close()
            return jsonify({'error': 'Teacher not found'}), 404

        print(f"✅ Found teacher: {teacher['username']}")

        # Get all class/subject assignments for this teacher
        cursor.execute("""
            SELECT DISTINCT subject_id, class_id
            FROM subject_teacher
            WHERE teacher_id = %s
            ORDER BY class_id, subject_id
        """, (teacher_id,))
        
        assignments = cursor.fetchall()
        print(f"✅ Found {len(assignments)} assignments")

        # Extract unique class and subject IDs
        class_ids = list(set(a['class_id'] for a in assignments if a['class_id'] is not None))
        subject_ids = list(set(a['subject_id'] for a in assignments if a['subject_id'] is not None))

        print(f"✅ Class IDs: {class_ids}, Subject IDs: {subject_ids}")

        cursor.close()
        conn.close()

        return jsonify({
            'success': True,
            'id': teacher['id'],
            'name': teacher['username'],
            'email': teacher['email'],
            'class_ids': class_ids,
            'subject_ids': subject_ids
        })
    
    except Exception as e:
        print(f"❌ Error fetching teacher: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/add-teacher', methods=['POST'])
def add_teacher():
    """Add a new teacher with multi-class and multi-subject assignments"""
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        teacher_name = (data.get('name') or '').strip()
        teacher_email = (data.get('email') or '').strip()
        teacher_password = (data.get('password') or '').strip()
        class_ids = data.get('class_ids', [])
        subject_ids = data.get('subject_ids', [])

        # Validation
        if not teacher_name or not teacher_password:
            return jsonify({'success': False, 'message': 'Name and password are required'}), 400
        
        if len(teacher_password) < 6:
            return jsonify({'success': False, 'message': 'Password must be at least 6 characters'}), 400
        
        if not class_ids or len(class_ids) == 0:
            return jsonify({'success': False, 'message': 'At least one class is required'}), 400
        
        if not subject_ids or len(subject_ids) == 0:
            return jsonify({'success': False, 'message': 'At least one subject is required'}), 400
        
        if teacher_email and '@' not in teacher_email:
            return jsonify({'success': False, 'message': 'Invalid email address'}), 400

        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Check if teacher already exists
        cursor.execute("SELECT id FROM teachers WHERE username = %s", (teacher_name,))
        existing_teacher = cursor.fetchone()
        
        if existing_teacher:
            teacher_id = existing_teacher['id']
            is_new_teacher = False
            print(f"ℹ️ Teacher '{teacher_name}' already exists with ID: {teacher_id}")
        else:
            from werkzeug.security import generate_password_hash
            hashed_password = generate_password_hash(teacher_password)
            
            cursor.execute("""
                INSERT INTO teachers (username, email, password)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (teacher_name, teacher_email or None, hashed_password))
            
            teacher_id = cursor.fetchone()['id']
            is_new_teacher = True
            print(f"✅ New teacher created with ID: {teacher_id}")

        # Create all subject_teacher links (cross join all class/subject pairs)
        assignments_added = 0
        for class_id in class_ids:
            for subject_id in subject_ids:
                # Check if assignment already exists
                cursor.execute("""
                    SELECT id FROM subject_teacher
                    WHERE teacher_id = %s AND subject_id = %s AND class_id = %s
                """, (teacher_id, subject_id, class_id))
                
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO subject_teacher (teacher_id, subject_id, class_id)
                        VALUES (%s, %s, %s)
                    """, (teacher_id, subject_id, class_id))
                    assignments_added += 1
                    print(f"✅ Added assignment: Teacher {teacher_id} -> Class {class_id}, Subject {subject_id}")

        conn.commit()
        cursor.close()
        conn.close()

        status = "created" if is_new_teacher else "assigned"
        print(f"✅ Teacher '{teacher_name}' {status} with {assignments_added} new assignments")
        
        return jsonify({
            'success': True,
            'message': f'Teacher "{teacher_name}" {status} successfully with {assignments_added} class-subject assignments',
            'teacher_id': teacher_id,
            'is_new': is_new_teacher,
            'assignments': assignments_added
        }), 201

    except Exception as e:
        print(f"❌ Error adding teacher: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/edit-teacher/<int:teacher_id>', methods=['PUT'])
def edit_teacher(teacher_id):
    """Edit teacher information and class/subject assignments"""
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip()
        password = (data.get('password') or '').strip()
        class_ids = data.get('class_ids', [])
        subject_ids = data.get('subject_ids', [])

        # Validation
        if not name:
            return jsonify({'success': False, 'message': 'Teacher name is required'}), 400
        
        if email and '@' not in email:
            return jsonify({'success': False, 'message': 'Invalid email address'}), 400
        
        if password and len(password) < 6:
            return jsonify({'success': False, 'message': 'Password must be at least 6 characters'}), 400
        
        if not class_ids or len(class_ids) == 0:
            return jsonify({'success': False, 'message': 'At least one class is required'}), 400
        
        if not subject_ids or len(subject_ids) == 0:
            return jsonify({'success': False, 'message': 'At least one subject is required'}), 400

        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Verify teacher exists
        cursor.execute("SELECT id FROM teachers WHERE id = %s", (teacher_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Teacher not found'}), 404

        # Update basic info
        if password:
            from werkzeug.security import generate_password_hash
            hashed_password = generate_password_hash(password)
            cursor.execute("""
                UPDATE teachers
                SET username = %s, email = %s, password = %s
                WHERE id = %s
            """, (name, email or None, hashed_password, teacher_id))
            print(f"✅ Updated teacher {teacher_id} with new password")
        else:
            cursor.execute("""
                UPDATE teachers
                SET username = %s, email = %s
                WHERE id = %s
            """, (name, email or None, teacher_id))
            print(f"✅ Updated teacher {teacher_id} (no password change)")

        # Remove old subject_teacher records
        cursor.execute("DELETE FROM subject_teacher WHERE teacher_id = %s", (teacher_id,))
        print(f"✅ Removed old assignments for teacher {teacher_id}")

        # Insert updated combinations
        assignments_added = 0
        for class_id in class_ids:
            for subject_id in subject_ids:
                cursor.execute("""
                    INSERT INTO subject_teacher (teacher_id, subject_id, class_id)
                    VALUES (%s, %s, %s)
                """, (teacher_id, subject_id, class_id))
                assignments_added += 1

        conn.commit()
        cursor.close()
        conn.close()

        print(f"✅ Added {assignments_added} new assignments for teacher {teacher_id}")

        return jsonify({
            'success': True,
            'message': f'Teacher updated successfully with {assignments_added} class-subject assignments'
        })

    except Exception as e:
        print(f"❌ Error updating teacher: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/delete-teacher/<int:teacher_id>', methods=['DELETE'])
def delete_teacher(teacher_id):
    """Delete a teacher and all associated records"""
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get teacher info for logging
        cursor.execute("SELECT username FROM teachers WHERE id = %s", (teacher_id,))
        teacher = cursor.fetchone()

        if not teacher:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Teacher not found'}), 404

        teacher_name = teacher['username']

        # Delete assignments first (foreign key constraint)
        cursor.execute("DELETE FROM subject_teacher WHERE teacher_id = %s", (teacher_id,))
        print(f"✅ Deleted all assignments for teacher {teacher_id}")

        # Delete teacher
        cursor.execute("DELETE FROM teachers WHERE id = %s", (teacher_id,))
        conn.commit()

        cursor.close()
        conn.close()

        print(f"✅ Teacher '{teacher_name}' deleted successfully")
        return jsonify({
            'success': True,
            'message': f'Teacher "{teacher_name}" deleted successfully'
        })

    except Exception as e:
        print(f"❌ Error deleting teacher: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/teacher-performance/<int:teacher_id>')
def teacher_performance(teacher_id):
    """Get performance metrics for a teacher across all their classes and subjects"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        term = session.get('term')
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get all class/subject assignments for this teacher
        cursor.execute("""
            SELECT DISTINCT st.class_id, c.name as class_name, 
                   st.subject_id, s.name as subject_name
            FROM subject_teacher st
            LEFT JOIN classes c ON st.class_id = c.id
            LEFT JOIN subjects s ON st.subject_id = s.id
            WHERE st.teacher_id = %s
            AND st.class_id IS NOT NULL
            ORDER BY c.name, s.name
        """, (teacher_id,))

        records = cursor.fetchall()
        print(f"✅ Found {len(records)} class/subject assignments for teacher {teacher_id}")

        if len(records) == 0:
            cursor.close()
            conn.close()
            print("⚠️ No valid assignments found for this teacher")
            return jsonify({
                'success': True,
                'performance': [],
                'message': 'Teacher has no class/subject assignments yet'
            })

        performance = []
        for r in records:
            if not r['class_id'] or not r['subject_id']:
                print(f"⚠️ Skipping invalid record: {r}")
                continue

            print(f"🟢 Calculating stats for {r['class_name']} - {r['subject_name']}")

            # FIXED: Join through students to get class_id context
            query = """
                SELECT AVG(CASE WHEN m.score >= 50 THEN 100 ELSE 0 END) AS pass_rate,
                       AVG(m.score) as average_mark,
                       COUNT(*) as total_marks
                FROM marks m
                INNER JOIN students st ON m.student_id = st.id
                WHERE m.subject_id = %s AND st.class_id = %s
            """
            params = [r['subject_id'], r['class_id']]

            if term:
                query += " AND m.term = %s"
                params.append(term)

            cursor.execute(query, params)
            stat = cursor.fetchone()
            print(f"   Stats: {stat}")

            pass_rate = round(float(stat['pass_rate']), 1) if stat and stat['pass_rate'] is not None else 0
            average_mark = round(float(stat['average_mark']), 1) if stat and stat['average_mark'] is not None else None
            total_marks = stat['total_marks'] if stat else 0

            performance.append({
                'class_id': r['class_id'],
                'class_name': r['class_name'] or 'Unknown Class',
                'subject_id': r['subject_id'],
                'subject_name': r['subject_name'] or 'Unknown Subject',
                'pass_rate': pass_rate,
                'average_mark': average_mark,
                'total_marks': total_marks
            })

        cursor.close()
        conn.close()

        print(f"✅ Returning {len(performance)} performance records")
        return jsonify({
            'success': True,
            'performance': performance
        })

    except Exception as e:
        print(f"❌ Error fetching teacher performance: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500




# ============================
# STUDENTS TAB API ROUTES
# ============================

@app.route('/api/get-students/<int:class_id>')
def get_students(class_id):
    """Get all students for a specific class with their performance data"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        term = session.get('term')
        
        # Verify class exists
        cursor.execute("SELECT name FROM classes WHERE id = %s", (class_id,))
        cls = cursor.fetchone()
        
        if not cls:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Class not found'}), 404
        
        # Get all students in this class
        cursor.execute("""
            SELECT s.id, s.firstname, s.surname
            FROM students s
            WHERE s.class_id = %s
            ORDER BY s.firstname, s.surname
        """, (class_id,))
        
        students = cursor.fetchall()
        
        def calculate_grade(score):
            """Calculate letter grade from numeric score"""
            if score >= 90:
                return 'A'
            elif score >= 80:
                return 'B'
            elif score >= 70:
                return 'C'
            elif score >= 60:
                return 'D'
            else:
                return 'F'
        
        students_data = []
        class_total_average = 0
        pass_count = 0
        total_students = len(students)
        
        for student in students:
            # Get all marks for this student
            if term:
                cursor.execute("""
                    SELECT m.score
                    FROM marks m
                    WHERE m.student_id = %s AND m.term = %s
                """, (student['id'], term))
            else:
                cursor.execute("""
                    SELECT m.score
                    FROM marks m
                    WHERE m.student_id = %s
                """, (student['id'],))
            
            grades_data = cursor.fetchall()
            
            if grades_data:
                scores = [g['score'] for g in grades_data]
                average = sum(scores) / len(scores)
                grade = calculate_grade(average)
                pass_count += 1 if grade in ['A', 'B', 'C'] else 0
            else:
                average = 0
                grade = 'N/A'
            
            students_data.append({
                'id': student['id'],
                'first_name': student['firstname'],
                'surname': student['surname'],
                'student_id': f"STU-{student['id']:04d}",
                'average': round(average, 2),
                'grade': grade,
                'num_subjects': len(grades_data)
            })
            
            class_total_average += average
        
        # Calculate class statistics
        class_average = (class_total_average / len(students)) if students else 0
        pass_rate = (pass_count / total_students * 100) if total_students > 0 else 0
        
        # Get top 5 students
        top_students = sorted(students_data, key=lambda x: x['average'], reverse=True)[:5]
        
        cursor.close()
        conn.close()
        
        print(f"✅ Fetched {len(students_data)} students for class {class_id}")
        
        return jsonify({
            'students': students_data,
            'class_average': round(class_average, 2),
            'pass_rate': round(pass_rate, 2),
            'top_students': top_students
        })
    
    except Exception as e:
        print(f"❌ Error fetching students: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/get-student/<int:student_id>')
def get_student(student_id):
    """Get detailed information about a specific student"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Get student basic info and class_id
        cursor.execute("""
            SELECT id, firstname, surname, class_id
            FROM students
            WHERE id = %s
        """, (student_id,))
        
        student = cursor.fetchone()
        
        if not student:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Student not found'}), 404
        
        # Get current term from session
        current_term = session.get('term')
        
        # Get marks for current term only
        if current_term:
            cursor.execute("""
                SELECT m.subject_id, s.name, m.score, m.term, m.comment
                FROM marks m
                JOIN subjects s ON m.subject_id = s.id
                WHERE m.student_id = %s AND m.term = %s
                ORDER BY s.name
            """, (student_id, current_term))
        else:
            # If no term selected, get all marks
            cursor.execute("""
                SELECT m.subject_id, s.name, m.score, m.term, m.comment
                FROM marks m
                JOIN subjects s ON m.subject_id = s.id
                WHERE m.student_id = %s
                ORDER BY s.name, m.term
            """, (student_id,))
        
        marks = cursor.fetchall()
        
        def calculate_grade(score):
            """Calculate letter grade from numeric score"""
            if score >= 90:
                return 'A+'
            elif score >= 80:
                return 'A'
            elif score >= 70:
                return 'B+'
            elif score >= 60:
                return 'B'
            elif score >= 50:
                return 'C'
            elif score >= 40:
                return 'D'
            else:
                return 'F'
        
        # Format subject scores
        subject_scores = []
        for mark in marks:
            subject_scores.append({
                'subject_id': mark['subject_id'],
                'subject_name': mark['name'],
                'score': round(mark['score'], 2),
                'grade': calculate_grade(mark['score']),
                'term': mark['term'],
                'comment': mark['comment'] or 'N/A'
            })
        
        # Get student's class
        cursor.execute("""
            SELECT c.name
            FROM classes c
            WHERE c.id = %s
        """, (student['class_id'],))
        
        class_result = cursor.fetchone()
        class_name = class_result['name'] if class_result else 'N/A'
        
        # Calculate overall average for current term
        if marks:
            average = sum([m['score'] for m in marks]) / len(marks)
        else:
            average = 0
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'student': {
                'id': student['id'],
                'first_name': student['firstname'],
                'surname': student['surname'],
                'student_id': f"STU-{student['id']:04d}",
                'class_id': student['class_id'],
                'class_name': class_name,
                'average': round(average, 2)
            },
            'subject_scores': subject_scores,
            'current_term': current_term or 'All Terms'
        })
    
    except Exception as e:
        print(f"❌ Error fetching student details: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/add-student', methods=['POST'])
def add_student():
    """Add a new student to a class"""
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        
        first_name = data.get('first_name', '').strip()
        surname = data.get('surname', '').strip()
        class_id = data.get('class_id')
        subjects = data.get('subjects', [])
        
        # Validate required fields
        if not all([first_name, surname, class_id]):
            return jsonify({'success': False, 'message': 'First name, surname, and class are required'}), 400
        
        if not subjects or len(subjects) == 0:
            return jsonify({'success': False, 'message': 'At least one subject is required'}), 400
        
        conn = get_database()
        cursor = conn.cursor()
        
        # Verify class exists
        cursor.execute("SELECT id FROM classes WHERE id = %s", (class_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Class not found'}), 400
        
        # Insert new student (ID is auto-generated)
        cursor.execute("""
            INSERT INTO students (firstname, surname, class_id)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (first_name, surname, class_id))
        
        new_student_id = cursor.fetchone()[0]
        print(f"✅ Created student with ID: {new_student_id}")
        
        # Add student to selected subjects
        if subjects and len(subjects) > 0:
            for subject_id in subjects:
                try:
                    cursor.execute("""
                        INSERT INTO student_subjects (student_id, subject_id)
                        VALUES (%s, %s)
                    """, (new_student_id, int(subject_id)))
                    print(f"✅ Added subject {subject_id} to student {new_student_id}")
                except Exception as subj_err:
                    print(f"⚠️ Warning: Could not add subject {subject_id}: {subj_err}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"✅ Student '{first_name} {surname}' added successfully to class {class_id}")
        return jsonify({'success': True, 'message': 'Student added successfully'})
    
    except Exception as e:
        print(f"❌ Error adding student: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route('/api/delete-student/<int:student_id>', methods=['DELETE'])
def delete_student(student_id):
    """Delete a student and all associated records"""
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        conn = get_database()
        cursor = conn.cursor()
        
        # Get student info for logging
        cursor.execute("SELECT firstname, surname FROM students WHERE id = %s", (student_id,))
        student = cursor.fetchone()
        
        if not student:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student_name = f"{student[0]} {student[1]}"
        
        # Delete from student_subjects (foreign key)
        cursor.execute("DELETE FROM student_subjects WHERE student_id = %s", (student_id,))
        
        # Delete from marks
        cursor.execute("DELETE FROM marks WHERE student_id = %s", (student_id,))
        
        # Delete student
        cursor.execute("DELETE FROM students WHERE id = %s", (student_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"✅ Student '{student_name}' deleted successfully")
        return jsonify({'success': True, 'message': 'Student deleted successfully'})
    
    except Exception as e:
        print(f"❌ Error deleting student: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route('/api/edit-student/<int:student_id>', methods=['PUT'])
def edit_student(student_id):
    """Edit student information and subjects"""
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        
        first_name = data.get('first_name', '').strip()
        surname = data.get('surname', '').strip()
        subjects = data.get('subjects', [])
        
        # Validate required fields
        if not all([first_name, surname]):
            return jsonify({'success': False, 'message': 'First name and surname are required'}), 400
        
        if not subjects or len(subjects) == 0:
            return jsonify({'success': False, 'message': 'At least one subject is required'}), 400
        
        conn = get_database()
        cursor = conn.cursor()
        
        # Verify student exists
        cursor.execute("SELECT id FROM students WHERE id = %s", (student_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        # Update student info
        cursor.execute("""
            UPDATE students
            SET firstname = %s, surname = %s
            WHERE id = %s
        """, (first_name, surname, student_id))
        
        # Delete old subject associations
        cursor.execute("DELETE FROM student_subjects WHERE student_id = %s", (student_id,))
        
        # Add new subject associations
        for subject_id in subjects:
            cursor.execute("""
                INSERT INTO student_subjects (student_id, subject_id)
                VALUES (%s, %s)
            """, (student_id, int(subject_id)))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"✅ Student {student_id} updated: {first_name} {surname}")
        return jsonify({'success': True, 'message': 'Student updated successfully'})
    
    except Exception as e:
        print(f"❌ Error editing student: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 400



# ============================
# CLASSES MANAGEMENT API ROUTES
# ============================
@app.route('/api/get-all-classes', methods=['GET'])
def get_all_classes():
    """Get all available classes"""
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("SELECT id, name FROM classes ORDER BY name ASC")
        classes = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'classes': [dict(c) for c in classes]
        })
    except Exception as e:
        print(f"❌ Error fetching classes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'classes': [], 'error': str(e)}), 500


@app.route('/api/get-subjects-for-classes', methods=['POST'])
def get_subjects_for_classes():
    """Get all subjects available for the selected classes"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        class_ids = data.get('class_ids', [])
        
        print(f"🟢 get_subjects_for_classes called with class_ids: {class_ids}")
        
        if not class_ids or len(class_ids) == 0:
            print("⚠️ No class IDs provided")
            return jsonify({'success': True, 'subjects': []})
        
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Query: Get subjects from class_subjects table
        query = """
            SELECT DISTINCT s.id, s.name
            FROM subjects s
            INNER JOIN class_subjects cs ON s.id = cs.subject_id
            WHERE cs.class_id = ANY(%s)
            ORDER BY s.name
        """
        
        print(f"🟢 Executing query with class_ids: {class_ids}")
        cursor.execute(query, (class_ids,))
        subjects = cursor.fetchall()
        
        print(f"✅ Found {len(subjects)} subjects for classes {class_ids}")
        
        cursor.close()
        conn.close()
        
        subjects_list = [dict(s) for s in subjects]
        print(f"✅ Subjects: {subjects_list}")
        
        return jsonify({
            'success': True,
            'subjects': subjects_list
        })
    
    except Exception as e:
        print(f"❌ Error in get_subjects_for_classes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'subjects': [], 'error': str(e)}), 500


@app.route('/api/get-class-subjects/<int:class_id>')
def get_class_subjects(class_id):
    """Get only subjects taught in a specific class"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Get subjects for this class only
        cursor.execute("""
            SELECT DISTINCT s.id, s.name
            FROM subjects s
            JOIN class_subjects cs ON s.id = cs.subject_id
            WHERE cs.class_id = %s
            ORDER BY s.name
        """, (class_id,))
        
        subjects = cursor.fetchall()
        
        subjects_data = [
            {'id': s['id'], 'name': s['name']}
            for s in subjects
        ]
        
        cursor.close()
        conn.close()
        
        print(f"✅ Fetched {len(subjects_data)} subjects for class {class_id}")
        return jsonify({'subjects': subjects_data})
    
    except Exception as e:
        print(f"❌ Error fetching class subjects: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/class-full-analytics')
def class_full_analytics():
    """Get full analytics for a specific class"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    class_name = request.args.get('class_name')
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Get class info
        cursor.execute("SELECT id, name, description FROM classes WHERE name = %s", (class_name,))
        cls = cursor.fetchone()
        
        if not cls:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Class not found'}), 404
        
        class_id = cls['id']
        
        # Get all students and their marks
        cursor.execute("""
            SELECT s.id, s.firstname, s.surname
            FROM students s
            WHERE s.class_id = %s
        """, (class_id,))
        
        students = cursor.fetchall()
        total_students = len(students)
        
        # Calculate grade distribution and statistics
        grade_distribution = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}
        total_average = 0
        pass_count = 0
        
        def calculate_grade(score):
            if score >= 90:
                return 'A'
            elif score >= 80:
                return 'B'
            elif score >= 70:
                return 'C'
            elif score >= 60:
                return 'D'
            else:
                return 'F'
        
        for student in students:
            cursor.execute("""
                SELECT AVG(score) as avg_score
                FROM marks
                WHERE student_id = %s
            """, (student['id'],))
            
            result = cursor.fetchone()
            avg = float(result['avg_score']) if (result and result['avg_score'] is not None) else 0
            grade = calculate_grade(avg)
            
            grade_distribution[grade] += 1
            total_average += avg
            if grade in ['A', 'B', 'C']:
                pass_count += 1
        
        class_average = total_average / total_students if total_students > 0 else 0
        pass_rate = (pass_count / total_students * 100) if total_students > 0 else 0
        
        # Get subject performance - FIX: Include subject id in SELECT
        cursor.execute("""
            SELECT s.id, s.name, COUNT(DISTINCT m.student_id) as student_count,
                   AVG(m.score) as average,
                   MAX(m.score) as highest,
                   MIN(m.score) as lowest
            FROM subjects s
            LEFT JOIN marks m ON s.id = m.subject_id
            LEFT JOIN students st ON m.student_id = st.id
            WHERE s.id IN (SELECT subject_id FROM class_subjects WHERE class_id = %s)
            GROUP BY s.id, s.name
        """, (class_id,))
        
        subjects = cursor.fetchall()
        subjects_data = []
        
        for subject in subjects:
            subject_id = subject['id']  # Now this will work
            
            cursor.execute("""
                SELECT COUNT(*) as pass_count
                FROM marks m
                WHERE m.subject_id = %s AND m.score >= 60
            """, (subject_id,))
            
            pass_result = cursor.fetchone()
            pass_rate_subject = (pass_result['pass_count'] / (subject['student_count'] or 1) * 100) if subject['student_count'] else 0
            
            subjects_data.append({
                'name': subject['name'],
                'student_count': subject['student_count'] or 0,
                'average': float(subject['average'] or 0),
                'highest': float(subject['highest'] or 0),
                'lowest': float(subject['lowest'] or 0),
                'pass_rate': round(pass_rate_subject, 2)
            })
        
        cursor.close()
        conn.close()
        
        print(f"✅ Fetched full analytics for class: {class_name}")
        return jsonify({
            'class': {
                'id': cls['id'],
                'name': cls['name'],
                'description': cls['description'] or '',
                'total_students': total_students,
                'class_average': round(class_average, 2),
                'pass_rate': round(pass_rate, 2),
                'grade_distribution': grade_distribution,
                'subjects': subjects_data
            }
        })
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/add-class', methods=['POST'])
def add_class():
    """Add a new class"""
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        
        class_name = data.get('name', '').strip()
        class_description = data.get('description', '').strip()
        subject_ids = data.get('subjects', [])
        
        print(f"Adding class: {class_name}")
        print(f"Subjects: {subject_ids}")
        
        # Validate required fields
        if not class_name:
            return jsonify({'success': False, 'message': 'Class name is required'}), 400
        
        if not subject_ids or len(subject_ids) == 0:
            return jsonify({'success': False, 'message': 'At least one subject is required'}), 400
        
        conn = get_database()
        cursor = conn.cursor()
        
        # Check if class already exists
        cursor.execute("SELECT id FROM classes WHERE name = %s", (class_name,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Class already exists'}), 400
        
        # Insert new class
        cursor.execute("""
            INSERT INTO classes (name, description)
            VALUES (%s, %s)
            RETURNING id
        """, (class_name, class_description or None))
        
        new_class_id = cursor.fetchone()[0]
        print(f"✅ Created class with ID: {new_class_id}")
        
        # Add subjects to class
        for subject_id in subject_ids:
            try:
                cursor.execute("""
                    INSERT INTO class_subjects (class_id, subject_id)
                    VALUES (%s, %s)
                """, (new_class_id, int(subject_id)))
                print(f"✅ Added subject {subject_id} to class {new_class_id}")
            except Exception as subj_err:
                print(f"⚠️ Warning: Could not add subject {subject_id}: {subj_err}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"✅ Class '{class_name}' created successfully")
        return jsonify({
            'success': True,
            'message': f'Class "{class_name}" created successfully',
            'class_id': new_class_id
        }), 201
    
    except Exception as e:
        print(f"❌ Error adding class: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 400
    

@app.route('/api/delete-class/<int:class_id>', methods=['DELETE'])
def delete_class(class_id):
    """Delete a class and all associated data"""
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Get class info for logging
        cursor.execute("SELECT name FROM classes WHERE id = %s", (class_id,))
        cls = cursor.fetchone()
        
        if not cls:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Class not found'}), 404
        
        class_name = cls['name']
        
        # Get all student IDs in this class
        cursor.execute("SELECT id FROM students WHERE class_id = %s", (class_id,))
        students = cursor.fetchall()
        student_ids = [s['id'] for s in students]
        
        print(f"Found {len(student_ids)} students to delete")
        
        # Delete marks for all students in this class (DELETE THIS FIRST)
        if student_ids:
            placeholders = ','.join(['%s'] * len(student_ids))
            cursor.execute(f"DELETE FROM marks WHERE student_id IN ({placeholders})", student_ids)
            print(f"✅ Deleted marks for {len(student_ids)} students")
        
        # Delete student_subjects associations
        if student_ids:
            placeholders = ','.join(['%s'] * len(student_ids))
            cursor.execute(f"DELETE FROM student_subjects WHERE student_id IN ({placeholders})", student_ids)
            print(f"✅ Deleted student_subjects associations")
        
        # Delete all students in the class
        cursor.execute("DELETE FROM students WHERE class_id = %s", (class_id,))
        print(f"✅ Deleted students from class")
        
        # Delete class_subjects associations
        cursor.execute("DELETE FROM class_subjects WHERE class_id = %s", (class_id,))
        print(f"✅ Deleted class_subjects associations")
        
        # Delete the class itself
        cursor.execute("DELETE FROM classes WHERE id = %s", (class_id,))
        print(f"✅ Deleted class record")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"✅ Class '{class_name}' deleted successfully with all associated data")
        return jsonify({
            'success': True,
            'message': f'Class "{class_name}" deleted successfully'
        }), 200
    
    except Exception as e:
        print(f"❌ Error deleting class: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 400
    
@app.route('/api/edit-class/<int:class_id>', methods=['PUT'])
def edit_class(class_id):
    """Edit a class"""
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        subjects = data.get('subjects', [])
        
        if not name:
            return jsonify({'success': False, 'message': 'Class name is required'}), 400
        
        if len(subjects) == 0:
            return jsonify({'success': False, 'message': 'At least one subject is required'}), 400
        
        conn = get_database()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE classes SET name = %s, description = %s WHERE id = %s",
                      (name, description, class_id))
        
        cursor.execute("DELETE FROM class_subjects WHERE class_id = %s", (class_id,))
        
        for subject_id in subjects:
            cursor.execute("INSERT INTO class_subjects (class_id, subject_id) VALUES (%s, %s)",
                          (class_id, int(subject_id)))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Class updated successfully'})
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 400
     
@app.route('/api/get-class/<int:class_id>')
def get_class(class_id):
    """Get class details for editing"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("SELECT id, name, description FROM classes WHERE id = %s", (class_id,))
        cls = cursor.fetchone()
        
        if not cls:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Class not found'}), 404
        
        cursor.execute("SELECT subject_id FROM class_subjects WHERE class_id = %s", (class_id,))
        subjects = [row['subject_id'] for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'class': {
                'id': cls['id'],
                'name': cls['name'],
                'description': cls['description']
            },
            'current_subjects': subjects
        })
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/get-all-subjects')
def get_all_subjects():
    """Get all available subjects"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("SELECT id, name FROM subjects ORDER BY name")
        subjects = cursor.fetchall()
        
        subjects_data = [
            {'id': s['id'], 'name': s['name']}
            for s in subjects
        ]
        
        cursor.close()
        conn.close()
        
        print(f"✅ Fetched {len(subjects_data)} subjects")
        return jsonify({'subjects': subjects_data}), 200
    
    except Exception as e:
        print(f"❌ Error fetching subjects: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/all-classes-analytics')
def all_classes_analytics():
    """Get analytics for all classes"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Get all classes
        cursor.execute("SELECT id, name, description FROM classes ORDER BY name")
        classes = cursor.fetchall()
        
        classes_data = []
        
        for cls in classes:
            class_id = cls['id']
            
            # Get subjects for this class
            cursor.execute("""
                SELECT s.id, s.name
                FROM subjects s
                JOIN class_subjects cs ON s.id = cs.subject_id
                WHERE cs.class_id = %s
                ORDER BY s.name
            """, (class_id,))
            
            subjects = cursor.fetchall()
            
            # Calculate statistics for each subject
            rows = []
            
            def calc_grade(score):
                if score >= 90:
                    return 'A'
                elif score >= 80:
                    return 'B'
                elif score >= 70:
                    return 'C'
                elif score >= 60:
                    return 'D'
                else:
                    return 'F'
            
            for subject in subjects:
                subject_id = subject['id']
                
                # Get all marks for this subject in this class
                cursor.execute("""
                    SELECT m.score
                    FROM marks m
                    JOIN students s ON m.student_id = s.id
                    WHERE m.subject_id = %s AND s.class_id = %s
                """, (subject_id, class_id))
                
                marks = cursor.fetchall()
                
                if marks:
                    scores = [m['score'] for m in marks]
                    avg = sum(scores) / len(scores)
                    
                    # Count grades
                    grade_counts = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}
                    for score in scores:
                        grade = calc_grade(score)
                        grade_counts[grade] += 1
                    
                    rows.append({
                        'subject': subject['name'],
                        'students': len(scores),
                        'A': grade_counts['A'],
                        'B': grade_counts['B'],
                        'C': grade_counts['C'],
                        'Failed': grade_counts['F'],
                        'average': round(avg, 2),
                        'grade': calc_grade(avg)
                    })
            
            # Get all students to calculate class average
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM students
                WHERE class_id = %s
            """, (class_id,))
            
            result = cursor.fetchone()
            total_students = result['count'] if result else 0
            
            # Calculate overall class average
            cursor.execute("""
                SELECT AVG(m.score) as avg
                FROM marks m
                JOIN students s ON m.student_id = s.id
                WHERE s.class_id = %s
            """, (class_id,))
            
            result = cursor.fetchone()
            overall_avg = float(result['avg']) if (result and result['avg'] is not None) else 0.0
            
            print(f"Class: {cls['name']}, Overall Average: {overall_avg}, Type: {type(overall_avg)}")
            
            classes_data.append({
                'id': cls['id'],
                'name': cls['name'],
                'description': cls['description'] or '',
                'rows': rows,
                'overall': round(overall_avg, 2)  # Ensure it's always a float
            })
        
        cursor.close()
        conn.close()
        
        print(f"✅ Fetched analytics for {len(classes_data)} classes")
        return jsonify(classes_data)
    
    except Exception as e:
        print(f"❌ Error in all_classes_analytics: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/add-subject', methods=['POST'])
def add_subject():
    """Add a new subject (admin only)"""
    if 'admin' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        subject_name = data.get('name', '').strip()

        if not subject_name:
            return jsonify({'success': False, 'message': 'Subject name is required'}), 400

        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # 1. Check for duplicate name
        cursor.execute("SELECT id FROM subjects WHERE LOWER(name) = LOWER(%s)", (subject_name,))
        existing = cursor.fetchone()
        if existing:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Subject already exists'}), 400

        # 2. Attempt to insert
        try:
            cursor.execute("INSERT INTO subjects (name) VALUES (%s) RETURNING id", (subject_name,))
            new_id = cursor.fetchone()['id']
            conn.commit()
        except psycopg2.errors.UniqueViolation as e:
            # If it's a primary key violation, reset the sequence and retry once
            conn.rollback()
            print(f"⚠️ Sequence conflict for subjects.id, resetting sequence...")
            cursor.execute("SELECT setval('subjects_id_seq', (SELECT MAX(id) FROM subjects));")
            cursor.execute("INSERT INTO subjects (name) VALUES (%s) RETURNING id", (subject_name,))
            new_id = cursor.fetchone()['id']
            conn.commit()
            print(f"✅ Sequence reset and subject inserted with id {new_id}")

        cursor.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Subject "{subject_name}" created',
            'subject': {'id': new_id, 'name': subject_name}
        }), 201

    except Exception as e:
        print(f"❌ Error adding subject: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Database error: ' + str(e)}), 500
    
@app.route('/api/filter-activity-log', methods=['POST'])
def filter_activity_log():
    """Filter activity logs by type and date range"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        activity_type = data.get('type')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        query = """
            SELECT timestamp, user_id, user_type, activity_type as type, 
                   description, status
            FROM activity_logs
            WHERE 1=1
        """
        params = []
        
        if activity_type:
            query += " AND activity_type LIKE %s"
            params.append(f"%{activity_type}%")
        
        if start_date:
            query += " AND timestamp >= %s"
            params.append(start_date)
        
        if end_date:
            query += " AND timestamp <= %s::date + interval '1 day'"
            params.append(end_date)
        
        query += " ORDER BY timestamp DESC LIMIT 100"
        
        cursor.execute(query, params)
        logs = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'logs': [dict(log) for log in logs]
        })
    
    except Exception as e:
        print(f"❌ Error filtering activity logs: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/download-activity-log')
def download_activity_log():
    """Download activity log as CSV"""
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("""
            SELECT timestamp, user_id, user_type, activity_type, description, status
            FROM activity_logs
            ORDER BY timestamp DESC
        """)
        
        logs = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Create CSV
        import csv
        import io
        from flask import send_file
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow(['Timestamp', 'User', 'User Type', 'Activity', 'Description', 'Status'])
        
        for log in logs:
            writer.writerow([
                log['timestamp'],
                log['user_id'],
                log['user_type'],
                log['activity_type'],
                log['description'],
                log['status']
            ])
        
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f"activity-log-{datetime.now().strftime('%Y-%m-%d')}.csv"
        )
    
    except Exception as e:
        print(f"❌ Error downloading activity log: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/log-activity', methods=['POST'])
def log_activity():
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        conn = get_database()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO activity_logs (timestamp, user_id, user_type, activity_type, description, status, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            data.get('timestamp'),
            session.get('admin'),   # username string
            'admin',
            data.get('type'),
            data.get('description'),
            data.get('status'),
            request.remote_addr
        ))

        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True}), 201

    except Exception as e:
        print(f"❌ Error logging activity: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
# ============================
# CALENDAR API
# ============================
@app.route('/api/events', methods=['GET'])
def get_events():
    if 'admin' not in session and 'teacher' not in session: 
        return jsonify({'error': 'Unauthorized'}), 401
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        if year and month:
            cursor.execute("""
                SELECT id, title, start_date as start, end_date as end, description, color, event_type as type
                FROM events
                WHERE EXTRACT(YEAR FROM start_date) = %s AND EXTRACT(MONTH FROM start_date) = %s
                ORDER BY start_date
            """, (year, month))
        else:
            cursor.execute("SELECT id, title, start_date as start, end_date as end, description, color, event_type as type FROM events ORDER BY start_date")
        events = cursor.fetchall()
        cursor.close(); conn.close()
        events_list = []
        for e in events:
            e_dict = dict(e)
            e_dict['start'] = e_dict['start'].isoformat()
            if e_dict['end']: e_dict['end'] = e_dict['end'].isoformat()
            events_list.append(e_dict)
        return jsonify({'events': events_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/events', methods=['POST'])
def create_event():
    if 'admin' not in session and 'teacher' not in session: 
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    try:
        conn = get_database()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO events (title, start_date, end_date, description, color, event_type, notify)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (data['title'], data['start'], data.get('end'), data.get('description'),
              data.get('color', '#3498db'), data.get('type', 'event'), data.get('notify', 'never')))
        event_id = cursor.fetchone()[0]
        conn.commit(); cursor.close(); conn.close()
        log_activity_internal('calendar_event_created', f"Created event: {data['title']}", 'Success')
        return jsonify({'success': True, 'event': {'id': event_id}})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/events/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    if 'admin' not in session and 'teacher' not in session: 
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        conn = get_database()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM events WHERE id = %s", (event_id,))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================
# SECURITY LOCK API
# ============================
@app.route('/api/portal-status', methods=['GET'])
def get_portal_status():
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute("SELECT portal, is_locked, last_changed FROM portal_status")
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        status = {'teacher_locked': True, 'student_locked': True}
        for row in rows:
            if row['portal'] == 'teacher':
                status['teacher_locked'] = row['is_locked']
                status['teacher_last_change'] = row['last_changed'].strftime('%Y-%m-%d %H:%M')
            elif row['portal'] == 'student':
                status['student_locked'] = row['is_locked']
                status['student_last_change'] = row['last_changed'].strftime('%Y-%m-%d %H:%M')
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/portal-status', methods=['POST'])
def update_portal_status():
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    portal = data.get('portal')
    action = data.get('action')
    reason = data.get('reason', '')
    if portal not in ('teacher', 'student'):
        return jsonify({'success': False, 'message': 'Invalid portal'}), 400
    is_locked = (action == 'lock')
    try:
        conn = get_database()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO portal_status (portal, is_locked, last_changed, changed_by)
            VALUES (%s, %s, NOW(), %s)
            ON CONFLICT (portal) DO UPDATE SET
                is_locked = EXCLUDED.is_locked,
                last_changed = EXCLUDED.last_changed,
                changed_by = EXCLUDED.changed_by
        """, (portal, is_locked, session.get('admin')))
        cursor.execute("""
            INSERT INTO lock_history (portal, action, reason, performed_by)
            VALUES (%s, %s, %s, %s)
        """, (portal, action, reason, session.get('admin')))
        conn.commit(); cursor.close(); conn.close()
        log_activity_internal(f'{portal}_portal_{action}', f'{portal} portal {action}ed', 'Success')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/lock-history')
def lock_history():
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute("SELECT portal, action, reason, performed_by, timestamp FROM lock_history ORDER BY timestamp DESC LIMIT 20")
        history = cursor.fetchall()
        cursor.close(); conn.close()
        return jsonify({'history': [dict(h) for h in history]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================
# ACTIVITY LOG API
# ============================
@app.route('/api/activity-stats')
def activity_stats():
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        today = datetime.now().date()
        cursor.execute("SELECT COUNT(*) as marks_entered FROM activity_logs WHERE activity_type LIKE '%%mark_entry%%' AND DATE(timestamp) = %s", (today,))
        marks = cursor.fetchone()['marks_entered']
        cursor.execute("SELECT COUNT(DISTINCT user_id) as teacher_logins FROM activity_logs WHERE user_type = 'teacher' AND activity_type LIKE '%%login%%' AND DATE(timestamp) = %s", (today,))
        logins = cursor.fetchone()['teacher_logins']
        cursor.execute("SELECT COUNT(*) as student_views FROM activity_logs WHERE user_type = 'student' AND activity_type = 'portal_access' AND DATE(timestamp) = %s", (today,))
        views = cursor.fetchone()['student_views']
        cursor.execute("SELECT is_locked FROM portal_status WHERE portal = 'teacher'")
        row = cursor.fetchone()
        teacher_locked = row['is_locked'] if row else True
        cursor.close(); conn.close()
        return jsonify({'marks_entered': marks, 'teacher_logins': logins, 'student_views': views, 'portal_status': 'LOCKED' if teacher_locked else 'UNLOCKED'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def log_activity_internal(activity_type, description, status):
    try:
        conn = get_database()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO activity_logs (timestamp, user_id, user_type, activity_type, description, status)
            VALUES (NOW(), %s, 'admin', %s, %s, %s)
        """, (session.get('admin'), activity_type, description, status))
        conn.commit(); cursor.close(); conn.close()
    except Exception as e:
        print(f"⚠️ Failed to log activity: {e}")

@app.route('/api/activity-log')
def get_activity_log():
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = get_database()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        activity_type = request.args.get('type')
        start_date = request.args.get('start')
        end_date = request.args.get('end')

        query = """
            SELECT timestamp, user_id, user_type, activity_type, description, status, ip_address
            FROM activity_logs
            WHERE 1=1
        """
        params = []

        if activity_type:
            query += " AND activity_type = %s"
            params.append(activity_type)
        if start_date:
            query += " AND DATE(timestamp) >= %s"
            params.append(start_date)
        if end_date:
            query += " AND DATE(timestamp) <= %s"
            params.append(end_date)

        query += " ORDER BY timestamp DESC LIMIT 100"

        cursor.execute(query, params)
        logs = cursor.fetchall()

        formatted = []
        for log in logs:
            formatted.append({
                'timestamp': log['timestamp'].isoformat() if log['timestamp'] else None,
                'user_type': log['user_type'],
                'user_name': log['user_id'],
                'user_id': log['user_id'],
                'activity_type': log['activity_type'],
                'details': log['description'],
                'status': log['status'],
                'ip': log['ip_address']
            })

        cursor.close()
        conn.close()
        return jsonify({'logs': formatted})

    except Exception as e:
        print(f"❌ Error fetching activity log: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
#LOGOUT
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

#run app
if __name__=='_main_':
 app.run(debug=True,)

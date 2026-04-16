from flask import Flask, render_template, request, redirect, session, jsonify, send_file
import psycopg2
import psycopg2.extras
import os
from datetime import datetime
from functools import wraps
import io
from fpdf import FPDF
from fpdf.enums import XPos, YPos

app = Flask(__name__)
app.secret_key = 'tafara victor'


# ---------- DATABASE ----------
def get_database():
    if not all([
        os.getenv("DB_HOST"),
        os.getenv("DB_USER"),
        os.getenv("DB_PASSWORD"),
        os.getenv("DB_NAME")
    ]):
        raise Exception("Database environment variables missing!")

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", 5432),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME"),
        cursor_factory=psycopg2.extras.DictCursor
    )
def is_student_portal_locked():
    conn = get_database()
    cursor = conn.cursor()
    cursor.execute("SELECT is_locked FROM portal_status WHERE portal = 'student'")
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else True


# ---------- LOGIN REQUIRED DECORATOR ----------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'student_id' not in session:
            return redirect('/')
        return f(*args, **kwargs)
    return decorated_function


# ---------- ERROR HANDLERS ----------
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    print(f"Internal Server Error: {error}")
    return render_template('500.html'), 500


# ---------- STUDENT LOGIN ----------
@app.route('/', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        try:
            firstname = request.form.get('firstname', '').strip()
            surname = request.form.get('surname', '').strip()
            student_id = request.form.get('id', '').strip()
            term = request.form.get('term', '')

            if not all([firstname, surname, student_id, term]):
                return render_template('student_login.html', error='All fields are required'), 400

            conn = get_database()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM students 
                WHERE LOWER(firstname)=%s AND LOWER(surname)=%s AND id=%s
            """, (firstname.lower(), surname.lower(), student_id))
            student = cursor.fetchone()
            conn.close()

            if student:
                # 🔒 STUDENT PORTAL LOCK CHECK
                if is_student_portal_locked():
                    return render_template('student_login.html', 
                        error='⚠️ The student portal is currently locked. Results are not available at this time.'), 403

                session['student_id'] = student['id']
                session['student_name'] = f"{student['firstname']} {student['surname']}"
                session['term'] = term
                session['login_time'] = datetime.now().isoformat()
                return redirect('/student_portal')
            else:
                return render_template('student_login.html', error='Invalid credentials. Please try again.'), 401

        except Exception as e:
            print(f"Login error: {str(e)}")
            return render_template('student_login.html', error='An error occurred. Please try again.'), 500

    return render_template('student_login.html')

# ---------- STUDENT PORTAL ----------
@app.route('/student_portal')
@login_required
def student_portal():
    # 🔒 Check portal lock on every access
    if is_student_portal_locked():
        session.clear()
        return redirect('/?error=portal_locked')
    
    try:
        student_id = session.get('student_id')
        term = session.get('term')

        conn = get_database()
        cursor = conn.cursor()

        # Student info
        cursor.execute("""
            SELECT s.*, c.name AS class_name
            FROM students s
            JOIN classes c ON s.class_id = c.id
            WHERE s.id = %s
        """, (student_id,))
        student = cursor.fetchone()

        if not student:
            conn.close()
            return redirect('/')

        # Marks + comments
        cursor.execute("""
            SELECT 
                sub.name AS subject, 
                m.score, 
                m.comment,
                CASE 
                    WHEN m.score >= 75 THEN 'A'
                    WHEN m.score >= 65 THEN 'B'
                    WHEN m.score >= 50 THEN 'C'
                    WHEN m.score >= 40 THEN 'D'
                    WHEN m.score >= 30 THEN 'E'
                    ELSE 'O'
                END AS grade
            FROM marks m
            JOIN subjects sub ON m.subject_id = sub.id
            WHERE m.student_id = %s AND m.term = %s
            ORDER BY sub.name
        """, (student_id, term))

        results = cursor.fetchall()

        # Calculate statistics
        subjects = [r['subject'] for r in results]
        scores = [r['score'] for r in results]
        grades = [r['grade'] for r in results]
        
        average = round(sum(scores) / len(scores), 2) if scores else 0
        
        # Grade distribution
        grade_counts = {
            'A': grades.count('A'),
            'B': grades.count('B'),
            'C': grades.count('C'),
            'D': grades.count('D'),
            'E': grades.count('E'),
            'O': grades.count('O')
        }
        
        # Best and worst subjects
        best_subject = max(results, key=lambda x: x['score']) if results else None
        worst_subject = min(results, key=lambda x: x['score']) if results else None
        
        # Pass rate
        pass_count = sum(1 for s in scores if s >= 40)
        pass_rate = round((pass_count / len(scores) * 100), 2) if scores else 0

        conn.close()

        return render_template(
            'student_results.html',
            student=student,
            results=results,
            term=term,
            subjects=subjects,
            scores=scores,
            grades=grades,
            average=average,
            grade_counts=grade_counts,
            best_subject=best_subject,
            worst_subject=worst_subject,
            pass_rate=pass_rate
        )
    except Exception as e:
        print(f"Error in student_portal: {str(e)}")
        return redirect('/')


# ---------- STUDENT PROFILE ----------
@app.route('/student_profile')
@login_required
def student_profile():
    try:
        student_id = session.get('student_id')
        conn = get_database()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.*, c.name AS class_name
            FROM students s
            JOIN classes c ON s.class_id = c.id
            WHERE s.id = %s
        """, (student_id,))
        
        student = cursor.fetchone()
        conn.close()

        if not student:
            return redirect('/')

        return render_template('student_profile.html', student=student)
    except Exception as e:
        print(f"Error in student_profile: {str(e)}")
        return redirect('/')


# ---------- HELPER FUNCTIONS ----------
def get_remarks(score):
    """Get remarks based on score"""
    if score >= 75:
        return "Excellent"
    elif score >= 65:
        return "Very Good"
    elif score >= 50:
        return "Good"
    elif score >= 40:
        return "Satisfactory"
    elif score >= 30:
        return "Fair"
    else:
        return "Poor"


def get_grade_color(grade):
    """Get RGB color based on grade"""
    colors = {
        'A': (34, 139, 34),      # Forest Green
        'B': (70, 130, 180),     # Steel Blue
        'C': (255, 165, 0),      # Orange
        'D': (184, 134, 11),     # Dark Goldenrod
        'E': (220, 20, 60),      # Crimson
        'O': (178, 34, 34)       # Firebrick
    }
    return colors.get(grade, (0, 0, 0))


# ---------- GENERATE LEGENDARY PDF ----------
def generate_pdf(student, results, term):
    """Generate LEGENDARY enterprise-grade PDF report"""
    try:
        pdf = FPDF('P', 'mm', 'A4')
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=12)
        
        # ========== PREMIUM HEADER SECTION ==========
        # Top gradient-like background effect
        pdf.set_fill_color(15, 32, 97)  # Deep Navy
        pdf.rect(0, 0, 210, 45, 'F')
        
        # Logo placement
        logo_path = 'static/funda.png'
        if os.path.exists(logo_path):
            pdf.image(logo_path, x=12, y=5, w=28, h=28)
        
        # School info on right
        pdf.set_font("Helvetica", "B", 22)
        pdf.set_text_color(255, 215, 0)  # Gold
        pdf.set_xy(50, 8)
        pdf.cell(150, 6, "FIRST CLASS HIGH SCHOOL", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(173, 216, 230)  # Light Blue
        pdf.set_xy(50, 15)
        pdf.cell(150, 5, "Excellence in Education - Shaping Tomorrow's Leaders", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(200, 200, 200)
        pdf.set_xy(50, 21)
        pdf.cell(150, 4, "Accredited | ISO Certified | Award-Winning Institution", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        # Decorative accent bar
        pdf.set_fill_color(255, 215, 0)
        pdf.rect(0, 40, 210, 2, 'F')
        
        pdf.set_y(45)
        
        # ========== CERTIFICATE STYLE HEADER ==========
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(15, 32, 97)
        pdf.cell(0, 8, "OFFICIAL ACADEMIC TRANSCRIPT", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(70, 130, 180)
        pdf.cell(0, 6, term, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.ln(3)
        
        # ========== STUDENT PROFILE CARD ==========
        pdf.set_fill_color(240, 248, 255)
        pdf.rect(12, pdf.get_y(), 186, 42, 'F')
        
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(15, 32, 97)
        pdf.set_xy(15, pdf.get_y())
        pdf.cell(45, 6, "Student Name:", new_x=XPos.RIGHT, new_y=YPos.TOP)
        
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(130, 6, f"{student['firstname'].upper()} {student['surname'].upper()}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(15, 32, 97)
        pdf.set_x(15)
        pdf.cell(45, 6, "Student ID:", new_x=XPos.RIGHT, new_y=YPos.TOP)
        
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(130, 6, str(student['id']), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(15, 32, 97)
        pdf.set_x(15)
        pdf.cell(45, 6, "Class/Grade:", new_x=XPos.RIGHT, new_y=YPos.TOP)
        
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(130, 6, student['class_name'], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(15, 32, 97)
        pdf.set_x(15)
        pdf.cell(45, 6, "Report Date:", new_x=XPos.RIGHT, new_y=YPos.TOP)
        
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(130, 6, datetime.now().strftime("%d %B %Y"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.ln(3)
        
        # ========== PERFORMANCE METRICS ==========
        scores = [r['score'] for r in results]
        average = round(sum(scores) / len(scores), 2) if scores else 0
        pass_count = sum(1 for s in scores if s >= 40)
        pass_rate = round((pass_count / len(scores) * 100), 2) if scores else 0
        highest = max(scores) if scores else 0
        lowest = min(scores) if scores else 0
        
        # Determine overall performance
        if average >= 75:
            performance = "EXCELLENT"
            perf_color = (34, 139, 34)
        elif average >= 65:
            performance = "VERY GOOD"
            perf_color = (70, 130, 180)
        elif average >= 50:
            performance = "GOOD"
            perf_color = (255, 165, 0)
        else:
            performance = "SATISFACTORY"
            perf_color = (184, 134, 11)
        
        # Metrics cards
        pdf.set_font("Helvetica", "B", 9)
        metrics = [
            ("OVERALL GRADE", f"{average}/100", (15, 32, 97)),
            ("HIGHEST SCORE", f"{highest}", (34, 139, 34)),
            ("LOWEST SCORE", f"{lowest}", (220, 20, 60)),
            ("PASS RATE", f"{pass_rate}%", (70, 130, 180))
        ]
        
        card_width = 46
        x_pos = 12
        y_pos = pdf.get_y()
        
        for metric_name, metric_value, color in metrics:
            pdf.set_fill_color(color[0], color[1], color[2])
            pdf.rect(x_pos, y_pos, card_width, 18, 'F')
            
            pdf.set_text_color(255, 255, 255)
            pdf.set_xy(x_pos, y_pos + 2)
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(card_width, 4, metric_name, align="C")
            
            pdf.set_xy(x_pos, y_pos + 7)
            pdf.set_font("Helvetica", "B", 14)
            pdf.cell(card_width, 8, metric_value, align="C")
            
            x_pos += card_width + 1
        
        pdf.ln(21)
        
        # ========== SUBJECT PERFORMANCE TABLE ==========
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(15, 32, 97)
        pdf.cell(0, 8, "DETAILED SUBJECT PERFORMANCE", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
        
        # Table header with gradient effect
        pdf.set_fill_color(15, 32, 97)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 10)
        
        col_widths = [45, 20, 15, 35, 30]
        headers = ["SUBJECT", "SCORE", "GRADE", "COMMENTS", "PERFORMANCE"]
        
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 8, header, border=1, new_x=XPos.RIGHT, new_y=YPos.TOP, fill=True, align="C")
        pdf.ln()
        
        # Table rows
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 9)
        
        for idx, result in enumerate(results):
            # Alternate row colors
            if idx % 2 == 0:
                pdf.set_fill_color(245, 248, 255)
            else:
                pdf.set_fill_color(230, 245, 255)
            
            remarks = result['comment'] if result['comment'] else get_remarks(result['score'])
            grade = result['grade']
            grade_color = get_grade_color(grade)
            
            # Subject
            pdf.cell(col_widths[0], 8, result['subject'][:30], border=1, new_x=XPos.RIGHT, new_y=YPos.TOP, fill=True)
            
            # Score with background
            pdf.set_fill_color(200, 220, 255)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(col_widths[1], 8, f"{result['score']}", border=1, new_x=XPos.RIGHT, new_y=YPos.TOP, fill=True, align="C")
            
            # Grade with color
            pdf.set_fill_color(grade_color[0], grade_color[1], grade_color[2])
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(col_widths[2], 8, grade, border=1, new_x=XPos.RIGHT, new_y=YPos.TOP, fill=True, align="C")
            
            # Comments
            pdf.set_text_color(0, 0, 0)
            pdf.set_fill_color(245, 248, 255) if idx % 2 == 0 else pdf.set_fill_color(230, 245, 255)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(col_widths[3], 8, remarks[:25], border=1, new_x=XPos.RIGHT, new_y=YPos.TOP, fill=True)
            
            # Performance indicator
            status = "PASS" if result['score'] >= 40 else "FAIL"
            status_color = (34, 139, 34) if result['score'] >= 40 else (220, 20, 60)
            pdf.set_fill_color(status_color[0], status_color[1], status_color[2])
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(col_widths[4], 8, status, border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True, align="C")
        
        pdf.ln(4)
        
        # ========== GRADE LEGEND ==========
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(15, 32, 97)
        pdf.cell(0, 6, "GRADE SCALE & INTERPRETATION", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font("Helvetica", "B", 8)
        grade_data = [
            ("A", "90-100", "Excellent", "Outstanding mastery"),
            ("B", "80-89", "Very Good", "Strong understanding"),
            ("C", "70-79", "Good", "Solid comprehension"),
            ("D", "60-69", "Satisfactory", "Basic understanding"),
            ("E", "50-59", "Fair", "Requires improvement"),
            ("O", "0-49", "Poor", "Significant gaps")
        ]
        
        for grade, range_val, desc, detail in grade_data:
            grade_color = get_grade_color(grade)
            pdf.set_fill_color(grade_color[0], grade_color[1], grade_color[2])
            pdf.set_text_color(255, 255, 255)
            pdf.cell(10, 6, grade, border=1, new_x=XPos.RIGHT, new_y=YPos.TOP, fill=True, align="C")
            
            pdf.set_text_color(0, 0, 0)
            pdf.set_fill_color(240, 248, 255)
            pdf.cell(20, 6, range_val, border=1, new_x=XPos.RIGHT, new_y=YPos.TOP, fill=True, align="C")
            pdf.cell(50, 6, desc, border=1, new_x=XPos.RIGHT, new_y=YPos.TOP, fill=True)
            pdf.cell(0, 6, detail, border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        
        pdf.ln(5)
        
        # ========== PERFORMANCE SUMMARY BOX ==========
        pdf.set_fill_color(15, 32, 97)
        pdf.rect(12, pdf.get_y(), 186, 20, 'F')
        
        pdf.set_text_color(255, 215, 0)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_xy(15, pdf.get_y() + 3)
        pdf.cell(0, 6, f"OVERALL PERFORMANCE: {performance}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_text_color(173, 216, 230)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_x(15)
        pdf.cell(0, 5, f"Average Score: {average}/100 | Subjects Passed: {pass_count}/{len(results)} | Pass Rate: {pass_rate}%", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_text_color(200, 200, 200)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_x(15)
        pdf.cell(0, 5, "This transcript certifies the academic performance of the named student and is issued as an official record.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.ln(5)
        
        # ========== FOOTER SECTION ==========
        pdf.set_draw_color(255, 215, 0)
        pdf.set_line_width(2)
        pdf.line(12, pdf.get_y(), 198, pdf.get_y())
        
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(15, 32, 97)
        pdf.cell(0, 4, "VERIFICATION & AUTHENTICITY", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 3, f"Document ID: FCHS-{student['id']}-{datetime.now().strftime('%Y%m%d')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 3, f"Generated: {datetime.now().strftime('%d %B %Y at %H:%M:%S')} | System: Official Academic Management System", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 3, "This is an official document. Unauthorized reproduction is prohibited.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        # Return PDF
        pdf_output = pdf.output()
        pdf_buffer = io.BytesIO(pdf_output)
        
        print("LEGENDARY PDF generated successfully!")
        return pdf_buffer
    
    except Exception as e:
        print(f"Error generating PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        raise


# ---------- DOWNLOAD RESULTS AS PDF ----------
@app.route('/download_results', methods=['GET'])
@login_required
def download_results():
    """Download student results as PDF"""
    try:
        student_id = session.get('student_id')
        term = session.get('term')

        if not student_id or not term:
            return redirect('/student_portal')

        conn = get_database()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.*, c.name AS class_name
            FROM students s
            JOIN classes c ON s.class_id = c.id
            WHERE s.id = %s
        """, (student_id,))
        student = cursor.fetchone()

        if not student:
            conn.close()
            return redirect('/student_portal')

        cursor.execute("""
            SELECT 
                sub.name AS subject, 
                m.score, 
                m.comment,
                CASE 
                    WHEN m.score >= 75 THEN 'A'
                    WHEN m.score >= 65 THEN 'B'
                    WHEN m.score >= 50 THEN 'C'
                    WHEN m.score >= 40 THEN 'D'
                    WHEN m.score >= 30 THEN 'E'
                    ELSE 'O'
                END AS grade
            FROM marks m
            JOIN subjects sub ON m.subject_id = sub.id
            WHERE m.student_id = %s AND m.term = %s
            ORDER BY sub.name
        """, (student_id, term))

        results = cursor.fetchall()
        conn.close()

        if not results:
            return redirect('/student_portal')

        pdf_buffer = generate_pdf(student, results, term)

        filename = f"ACADEMIC_TRANSCRIPT_{student['firstname']}_{student['surname']}_{term.replace(' ', '_')}.pdf"

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        print(f"Error: {str(e)}")
        return "Error generating PDF", 500


# ---------- LOGOUT ----------
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# ---------- API ENDPOINTS ----------
@app.route('/api/student_data')
@login_required
def api_student_data():
    try:
        student_id = session.get('student_id')
        term = session.get('term')

        conn = get_database()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT sub.name AS subject, m.score
            FROM marks m
            JOIN subjects sub ON m.subject_id = sub.id
            WHERE m.student_id = %s AND m.term = %s
            ORDER BY sub.name
        """, (student_id, term))

        results = cursor.fetchall()
        conn.close()

        return jsonify({
            'subjects': [r['subject'] for r in results],
            'scores': [r['score'] for r in results]
        })
    except Exception as e:
        return jsonify({'error': 'Failed to fetch data'}), 500


# ---------- RUN ----------
if __name__ == '__main__':
    app.run(debug=True, port=5001)
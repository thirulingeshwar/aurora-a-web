import requests
from datetime import datetime

BASE_URL = "http://localhost:5000"

def test_individual_no_class():
    session = requests.Session()
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"Testing Date: {today_str}")

    # 1. Login as admin
    print("\n--- 1. Login as Admin ---")
    resp = session.post(f"{BASE_URL}/api/login", json={
        "username": "admin",
        "password": "admin@123"
    })
    print("Login Status:", resp.status_code)
    assert resp.json().get("success") is True

    # 2. Impersonate Staff (thirulingeshwar)
    print("\n--- 2. Impersonate Staff ---")
    resp = session.post(f"{BASE_URL}/api/admin_impersonate", json={
        "username": "thirulingeshwar",
        "password": "thiruli334"
    })
    print("Impersonate Status:", resp.status_code)
    assert resp.json().get("success") is True

    # 3. Clean up existing student with target phone if any
    resp = session.get(f"{BASE_URL}/api/students")
    students = resp.json()
    for s in students:
        if s.get("phone") == "7776665554":
            print(f"Found existing test student {s['name']} (ID: {s['id']}), deleting...")
            session.delete(f"{BASE_URL}/api/students/{s['id']}")

    # 4. Create Student with period-wise timetable
    print("\n--- 4. Register Student ---")
    student_payload = {
        "name": "Test No Class Student",
        "phone": "7776665554",
        "class": "Biology Class",
        "branch": "Science",
        "parentName": "Parent Name",
        "parentPhone": "0987654321",
        "address": "123 Street",
        "totalClassDays": 30,
        "inTime": "09:00",
        "outTime": "10:00",
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "feeAmount": 2500,
        "minAttendanceLimit": 75,
        "timetable": [
            {"startTime": "09:00", "endTime": "10:00", "subject": "Biology"}
        ]
    }
    resp = session.post(f"{BASE_URL}/api/students", json=student_payload)
    print("Register Status:", resp.status_code)
    student_data = resp.json().get("student")
    assert student_data is not None
    student_id = student_data["id"]

    # 5. Mark Attendance as "No Class" with custom reason
    print("\n--- 5. Save attendance as 'No Class' with custom reason ---")
    attendance_payload = {
        "date": today_str,
        "attendance": [
            {
                "studentId": student_id,
                "studentName": "Test No Class Student",
                "class": "Biology Class",
                "branch": "Science",
                "status": "No Class",
                "inTime": "09:00",
                "outTime": "10:00",
                "startTime": "09:00",
                "endTime": "10:00",
                "subject": "Biology",
                "date": today_str,
                "reason": "Teacher Sick Leave",
                "remarks": "No Class (Teacher Sick Leave)"
            }
        ]
    }
    resp = session.post(f"{BASE_URL}/api/attendance", json=attendance_payload)
    print("Save Attendance Status:", resp.status_code)
    print("Save Attendance Response:", resp.json())
    assert resp.status_code == 201

    # 6. Verify marked record
    print("\n--- 6. Verify marked record ---")
    resp = session.get(f"{BASE_URL}/api/attendance?date={today_str}")
    records = [r for r in resp.json() if r["studentId"] == student_id]
    assert len(records) == 1
    record = records[0]
    print(f"Record: Status={record.get('status')}, Reason={record.get('reason')}, Remarks={record.get('remarks')}")
    assert record.get("status") == "No Class"
    assert record.get("reason") == "Teacher Sick Leave"
    assert record.get("remarks") == "No Class (Teacher Sick Leave)"

    # 7. Clean up Student
    print("\n--- 7. Clean up test student ---")
    del_resp = session.delete(f"{BASE_URL}/api/students/{student_id}")
    print("Clean up Status:", del_resp.status_code)

    print("\n=== ALL INDIVIDUAL NO CLASS TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    test_individual_no_class()

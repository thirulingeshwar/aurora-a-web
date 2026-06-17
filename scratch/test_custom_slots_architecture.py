import requests
from datetime import datetime

BASE_URL = "http://localhost:5000"

def test_custom_slots_architecture():
    session = requests.Session()
    test_date = "2026-06-22"  # A Monday

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
        if s.get("phone") == "6665554443":
            print(f"Found existing test student {s['name']} (ID: {s['id']}), deleting...")
            session.delete(f"{BASE_URL}/api/students/{s['id']}")

    # 4. Create Student with period-wise timetable (Monday Chemistry 09:00 - 10:00)
    print("\n--- 4. Register Student ---")
    student_payload = {
        "name": "Test Slots Student",
        "phone": "6665554443",
        "class": "Chemistry Class",
        "branch": "Science",
        "parentName": "Parent Name",
        "parentPhone": "0987654321",
        "address": "123 Street",
        "totalClassDays": 30,
        "inTime": "09:00",
        "outTime": "10:00",
        "days": ["Monday"],
        "feeAmount": 2500,
        "minAttendanceLimit": 75,
        "timetable": [
            {"startTime": "09:00", "endTime": "10:00", "subject": "Chemistry"}
        ]
    }
    resp = session.post(f"{BASE_URL}/api/students", json=student_payload)
    print("Register Status:", resp.status_code)
    student_data = resp.json().get("student")
    assert student_data is not None
    student_id = student_data["id"]

    # 5. Attempt overlapping custom class slot: Chemistry is 09:00 - 10:00, custom class is 09:30 - 10:30
    print("\n--- 5. Attempt overlapping custom class slot ---")
    overlap_payload = {
        "studentId": student_id,
        "date": test_date,
        "startTime": "09:30",
        "endTime": "10:30",
        "subject": "Chemistry Overlap"
    }
    resp = session.post(f"{BASE_URL}/api/custom-class-slots", json=overlap_payload)
    print("Overlap Response Status:", resp.status_code)
    print("Overlap Response JSON:", resp.json())
    assert resp.status_code == 400
    assert "already has a class" in resp.json().get("error")

    # 6. Create non-overlapping custom class slot: 11:00 - 12:00
    print("\n--- 6. Create non-overlapping custom class slot ---")
    ok_payload = {
        "studentId": student_id,
        "date": test_date,
        "startTime": "11:00",
        "endTime": "12:00",
        "subject": "Ad-hoc Math Extra"
    }
    resp = session.post(f"{BASE_URL}/api/custom-class-slots", json=ok_payload)
    print("Succeeded custom slot Status:", resp.status_code)
    print("Succeeded custom slot JSON:", resp.json())
    assert resp.status_code == 201
    custom_slot_id = resp.json().get("slot").get("id")

    # 7. Attempt to overlap with the custom class slot: 11:30 - 12:30 (overlaps with 11:00-12:00)
    print("\n--- 7. Attempt custom-custom overlap ---")
    custom_overlap_payload = {
        "studentId": student_id,
        "date": test_date,
        "startTime": "11:30",
        "endTime": "12:30",
        "subject": "Chemistry Overlap 2"
    }
    resp = session.post(f"{BASE_URL}/api/custom-class-slots", json=custom_overlap_payload)
    print("Custom overlap Status:", resp.status_code)
    print("Custom overlap JSON:", resp.json())
    assert resp.status_code == 400

    # 8. Query calendar attendance and verify custom slot exists
    print("\n--- 8. Verify slots in Calendar ---")
    resp = session.get(f"{BASE_URL}/api/calendar-attendance?start={test_date}&end={test_date}")
    events = [e for e in resp.json() if e["studentId"] == student_id]
    print(f"Calendar events found on {test_date}:")
    for e in events:
        print(f"Event ID: {e.get('id')} | Subject: {e.get('subject')} | Time: {e.get('startTime')}-{e.get('endTime')} | Status: {e.get('status')}")
    assert len(events) == 2  # timetable slot + custom class slot
    
    # 9. Perform Reset (soft delete) of custom slot
    print("\n--- 9. Soft-delete custom class slot ---")
    resp = session.delete(f"{BASE_URL}/api/attendance/{custom_slot_id}")
    print("Soft-delete Status:", resp.status_code)
    print("Soft-delete Response:", resp.json())
    assert resp.status_code == 200

    # 10. Query calendar again and verify only regular timetable slot is left
    print("\n--- 10. Verify slots in Calendar after soft delete ---")
    resp = session.get(f"{BASE_URL}/api/calendar-attendance?start={test_date}&end={test_date}")
    events = [e for e in resp.json() if e["studentId"] == student_id]
    print(f"Calendar events found after deletion:")
    for e in events:
        print(f"Event ID: {e.get('id')} | Subject: {e.get('subject')} | Time: {e.get('startTime')}-{e.get('endTime')} | Status: {e.get('status')}")
    assert len(events) == 1
    assert events[0]["subject"] == "Chemistry"

    # 11. Clean up Student
    print("\n--- 11. Clean up test student ---")
    del_resp = session.delete(f"{BASE_URL}/api/students/{student_id}")
    print("Clean up Status:", del_resp.status_code)

    print("\n=== ALL CUSTOM SLOTS ARCHITECTURE TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    test_custom_slots_architecture()

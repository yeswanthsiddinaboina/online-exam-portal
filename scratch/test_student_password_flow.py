import sys
import os
sys.path.insert(0, r"D:\secure-exam-system")

from backend.app import create_app
from backend.models import db, User, PasswordResetRequest

app = create_app()

with app.app_context():
    client = app.test_client()

    print("--- 1. Testing Student Registration with Password ---")
    reg_email = "test_student_pw@gmail.com"
    # Clean up old test user if exists
    old = User.query.filter_by(email=reg_email).first()
    if old:
        PasswordResetRequest.query.filter_by(user_id=old.id).delete()
        db.session.delete(old)
        db.session.commit()

    reg_res = client.post("/api/auth/register-student", json={
        "first_name": "Test Student",
        "email": reg_email,
        "password": "mySecurePassword123"
    })
    print("Registration Response:", reg_res.status_code, reg_res.get_json())
    assert reg_res.status_code == 201

    user = User.query.filter_by(email=reg_email).first()
    user.registration_status = "APPROVED"
    user.last_name = "STU9999"
    db.session.commit()
    print(f"User approved: {user.email}, User ID: {user.last_name}")

    print("\n--- 2. Testing Student Login with Incorrect Password ---")
    bad_login = client.post("/api/auth/login", json={
        "identifier": reg_email,
        "password": "wrongpassword"
    })
    print("Bad Login Response:", bad_login.status_code, bad_login.get_json())
    assert bad_login.status_code == 401

    print("\n--- 3. Testing Student Login with Gmail ID ---")
    good_login_email = client.post("/api/auth/login", json={
        "identifier": reg_email,
        "password": "mySecurePassword123"
    })
    print("Good Login (Email):", good_login_email.status_code, good_login_email.get_json().get("success"))
    assert good_login_email.status_code == 200

    print("\n--- 4. Testing Student Login with User ID ---")
    good_login_uid = client.post("/api/auth/login", json={
        "identifier": "STU9999",
        "password": "mySecurePassword123"
    })
    print("Good Login (User ID):", good_login_uid.status_code, good_login_uid.get_json().get("success"))
    assert good_login_uid.status_code == 200

    print("\n--- 5. Testing Request Password Reset ---")
    reset_req_res = client.post("/api/auth/reset-password/request", json={
        "identifier": "STU9999"
    })
    print("Reset Request Response:", reset_req_res.status_code, reset_req_res.get_json())
    assert reset_req_res.status_code == 201

    print("\n--- 6. Testing Confirm Reset Before Admin Approval ---")
    early_reset = client.post("/api/auth/reset-password/confirm", json={
        "identifier": reg_email,
        "new_password": "brandNewPassword456"
    })
    print("Early Reset Response (Must be blocked):", early_reset.status_code, early_reset.get_json())
    assert early_reset.status_code == 403

    print("\n--- 7. Admin Approves Reset ---")
    reset_record = PasswordResetRequest.query.filter_by(user_id=user.id, status="PENDING").first()
    reset_record.status = "APPROVED"
    db.session.commit()
    print("Admin approved reset record ID:", reset_record.id)

    print("\n--- 8. Student Completes Password Reset ---")
    complete_reset = client.post("/api/auth/reset-password/confirm", json={
        "identifier": "STU9999",
        "new_password": "brandNewPassword456"
    })
    print("Complete Reset Response:", complete_reset.status_code, complete_reset.get_json())
    assert complete_reset.status_code == 200

    print("\n--- 9. Login with New Password ---")
    new_login = client.post("/api/auth/login", json={
        "identifier": "STU9999",
        "password": "brandNewPassword456"
    })
    print("New Login Response:", new_login.status_code, new_login.get_json().get("success"))
    assert new_login.status_code == 200

    # Cleanup test user
    PasswordResetRequest.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    print("\n=== ALL TEST CASES PASSED SUCCESSFULLY ===")

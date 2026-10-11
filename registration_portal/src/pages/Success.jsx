import React from 'react';
import { useLocation, Link } from 'react-router-dom';

function Success() {
  const location = useLocation();

  // Retrieve registration info passed from Register page via navigation state
  const registrationData = location.state || {
    studentName: 'Rahul Kumar',
    rollNumber: '23CSE101',
    course: 'Advanced Java Programming',
    email: 'rahul@example.com',
    phone: '9876543210'
  };

  return (
    <div className="success-page">
      <div className="success-card">
        {/* Visual Confirmation Badge */}
        <div className="success-icon-badge">✓</div>

        <h2 className="success-title">Registration Successful!</h2>
        <p className="success-subtitle">
          Your course registration has been submitted and recorded successfully.
        </p>

        {/* Submitted Student Information Summary */}
        <div className="receipt-details">
          <div className="receipt-row">
            <span className="receipt-label">Student Name:</span>
            <span className="receipt-value">{registrationData.studentName}</span>
          </div>
          <div className="receipt-row">
            <span className="receipt-label">Roll Number:</span>
            <span className="receipt-value">{registrationData.rollNumber}</span>
          </div>
          <div className="receipt-row">
            <span className="receipt-label">Selected Course:</span>
            <span className="receipt-value">{registrationData.course}</span>
          </div>
          <div className="receipt-row">
            <span className="receipt-label">Email Address:</span>
            <span className="receipt-value">{registrationData.email}</span>
          </div>
          {registrationData.phone && (
            <div className="receipt-row">
              <span className="receipt-label">Phone Number:</span>
              <span className="receipt-value">{registrationData.phone}</span>
            </div>
          )}
        </div>

        {/* Action Navigation Buttons */}
        <div className="success-actions">
          <Link to="/" className="btn btn-primary">
            Back to Home
          </Link>
          <Link to="/courses" className="btn btn-outline">
            View Courses Again
          </Link>
        </div>
      </div>
    </div>
  );
}

export default Success;

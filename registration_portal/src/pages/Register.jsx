import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import InputField from '../components/InputField';
import { FALLBACK_COURSES } from './Courses';

function Register() {
  const location = useLocation();
  const navigate = useNavigate();

  // Controlled component state for the registration form
  const [formData, setFormData] = useState({
    studentName: '',
    email: '',
    rollNumber: '',
    phone: '',
    course: ''
  });

  // State for form validation errors
  const [errors, setErrors] = useState({});

  // State for available courses in the dropdown
  const [courseOptions, setCourseOptions] = useState(FALLBACK_COURSES);

  // State for API submission progress & server errors
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [serverError, setServerError] = useState('');

  // Pre-select course if user navigated here from CourseCard
  useEffect(() => {
    if (location.state && location.state.selectedCourse) {
      setFormData((prev) => ({
        ...prev,
        course: location.state.selectedCourse
      }));
    }
  }, [location.state]);

  // Fetch course list from API for dropdown
  useEffect(() => {
    fetch('http://localhost:5000/courses')
      .then((res) => {
        if (res.ok) {
          return res.json();
        }
        throw new Error('Failed to load courses');
      })
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setCourseOptions(data);
        }
      })
      .catch((err) => {
        console.warn('API unavailable for dropdown, using default courses:', err);
        setCourseOptions(FALLBACK_COURSES);
      });
  }, []);

  // Handle change for all controlled inputs
  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value
    }));

    // Clear individual error as user types
    if (errors[name]) {
      setErrors((prev) => ({
        ...prev,
        [name]: ''
      }));
    }
    if (serverError) {
      setServerError('');
    }
  };

  // Validate form inputs according to lab specifications
  const validateForm = () => {
    const newErrors = {};
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    const phoneRegex = /^[0-9]{10}$/;

    // 1. Student Name validation
    if (!formData.studentName.trim() || formData.studentName.trim().length < 3) {
      newErrors.studentName = 'Name must contain at least 3 characters.';
    }

    // 2. Email validation
    if (!formData.email.trim() || !emailRegex.test(formData.email.trim())) {
      newErrors.email = 'Please enter a valid email address.';
    }

    // 3. Roll Number validation
    if (!formData.rollNumber.trim()) {
      newErrors.rollNumber = 'Roll number is required.';
    }

    // 4. Phone Number validation
    if (!formData.phone.trim() || !phoneRegex.test(formData.phone.trim())) {
      newErrors.phone = 'Phone number must contain exactly 10 digits.';
    }

    // 5. Course Selection validation
    if (!formData.course) {
      newErrors.course = 'Please select a course.';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Handle form submission
  const handleSubmit = (e) => {
    e.preventDefault();
    setServerError('');

    // Step 1: Validate form
    const isValid = validateForm();
    if (!isValid) {
      return;
    }

    // Step 2: Show submitting state
    setIsSubmitting(true);

    const payload = {
      studentName: formData.studentName.trim(),
      email: formData.email.trim(),
      rollNumber: formData.rollNumber.trim(),
      phone: formData.phone.trim(),
      course: formData.course
    };

    // Step 3: Send POST request via fetch()
    fetch('http://localhost:5000/registrations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error('Registration failed');
        }
        return res.json();
      })
      .then((submittedData) => {
        setIsSubmitting(false);
        // Step 4: Navigate to Success page with submitted info
        navigate('/success', {
          state: {
            studentName: submittedData.studentName || payload.studentName,
            rollNumber: submittedData.rollNumber || payload.rollNumber,
            course: submittedData.course || payload.course,
            email: submittedData.email || payload.email,
            phone: submittedData.phone || payload.phone
          }
        });
      })
      .catch((err) => {
        console.error('Submission error:', err);
        setIsSubmitting(false);
        // Display API failure message as required
        setServerError('Registration failed. Please try again.');
      });
  };

  return (
    <div className="register-page">
      <div className="form-card">
        <div className="page-header">
          <h2 className="page-title">Course Registration</h2>
          <p className="page-description">Fill in your details below to complete your registration.</p>
        </div>

        {/* Server / API Error Message */}
        {serverError && (
          <div className="form-server-error">
            ⚠️ {serverError}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          {/* Reusable InputField for Student Name */}
          <InputField
            label="Student Name"
            name="studentName"
            type="text"
            value={formData.studentName}
            onChange={handleChange}
            error={errors.studentName}
            placeholder="e.g. Rahul Kumar"
          />

          {/* Reusable InputField for Email */}
          <InputField
            label="Student Email"
            name="email"
            type="email"
            value={formData.email}
            onChange={handleChange}
            error={errors.email}
            placeholder="e.g. rahul@example.com"
          />

          {/* Reusable InputField for Roll Number */}
          <InputField
            label="Roll Number"
            name="rollNumber"
            type="text"
            value={formData.rollNumber}
            onChange={handleChange}
            error={errors.rollNumber}
            placeholder="e.g. 23CSE101"
          />

          {/* Reusable InputField for Phone Number */}
          <InputField
            label="Phone Number"
            name="phone"
            type="tel"
            value={formData.phone}
            onChange={handleChange}
            error={errors.phone}
            placeholder="e.g. 9876543210 (10 digits)"
          />

          {/* Controlled Dropdown for Course Selection */}
          <div className="form-group">
            <label htmlFor="course" className="form-label">
              Course Selection <span className="required-star">*</span>
            </label>
            <select
              id="course"
              name="course"
              value={formData.course}
              onChange={handleChange}
              className={`form-select ${errors.course ? 'input-error' : ''}`}
            >
              <option value="">-- Select Course --</option>
              {courseOptions.map((c) => (
                <option key={c.id || c.name} value={c.name}>
                  {c.name} ({c.code || 'Course'})
                </option>
              ))}
            </select>
            {errors.course && <span className="error-message">{errors.course}</span>}
          </div>

          {/* Submit Button */}
          <div className="form-actions">
            <button
              type="submit"
              disabled={isSubmitting}
              className="btn btn-primary btn-submit"
            >
              {isSubmitting ? 'Submitting Registration...' : 'Submit Registration'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default Register;

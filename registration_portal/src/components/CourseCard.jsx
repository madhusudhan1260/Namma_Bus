import React from 'react';
import { useNavigate } from 'react-router-dom';

// CourseCard receives course data via props
function CourseCard({ id, name, code, credits }) {
  const navigate = useNavigate();

  const handleRegisterClick = () => {
    // Navigate to /register and pass the selected course name in navigation state
    navigate('/register', {
      state: { selectedCourse: name }
    });
  };

  return (
    <div className="course-card">
      <div>
        <h3 className="course-name">{name}</h3>
        <div className="course-meta">
          <span className="badge badge-code">Code: {code}</span>
          <span className="badge badge-credits">{credits} Credits</span>
        </div>
      </div>
      
      <button 
        type="button" 
        onClick={handleRegisterClick} 
        className="btn btn-primary"
      >
        Register Course
      </button>
    </div>
  );
}

export default CourseCard;

import React, { useState, useEffect } from 'react';
import CourseCard from '../components/CourseCard';

// Fallback course dataset for local testing / offline demo
export const FALLBACK_COURSES = [
  { id: 1, name: 'Advanced Java Programming', code: 'CSE301', credits: 4 },
  { id: 2, name: 'Data Structures and Algorithms', code: 'CSE302', credits: 4 },
  { id: 3, name: 'Database Management Systems', code: 'CSE303', credits: 3 },
  { id: 4, name: 'Computer Networks', code: 'CSE304', credits: 3 },
  { id: 5, name: 'Web Technologies', code: 'CSE305', credits: 3 }
];

function Courses() {
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Fetch courses from mock REST API using fetch()
  const fetchCourses = () => {
    setLoading(true);
    setError(null);

    fetch('http://localhost:5000/courses')
      .then((response) => {
        if (!response.ok) {
          throw new Error('Server returned ' + response.status);
        }
        return response.json();
      })
      .then((data) => {
        setCourses(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to fetch courses:', err);
        setError('Unable to load courses. Please try again.');
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchCourses();
  }, []);

  const handleUseFallback = () => {
    setCourses(FALLBACK_COURSES);
    setError(null);
  };

  return (
    <div className="courses-page">
      <div className="page-header">
        <h2 className="page-title">Available Courses</h2>
        <p className="page-description">
          Select a course below to proceed directly with your semester registration.
        </p>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="state-message-box">
          <p className="loading-text">Loading courses...</p>
        </div>
      )}

      {/* Error State with Retry and Fallback Buttons */}
      {!loading && error && (
        <div className="state-message-box">
          <p className="error-text">{error}</p>
          <div style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
            <button type="button" onClick={fetchCourses} className="btn btn-primary">
              Retry
            </button>
            <button type="button" onClick={handleUseFallback} className="btn btn-secondary">
              Use Fallback Data
            </button>
          </div>
        </div>
      )}

      {/* Course List Grid */}
      {!loading && !error && (
        <div className="courses-grid">
          {courses.map((course) => (
            <CourseCard
              key={course.id}
              id={course.id}
              name={course.name}
              code={course.code}
              credits={course.credits}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default Courses;

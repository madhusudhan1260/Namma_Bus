import React from 'react';
import { Link } from 'react-router-dom';

function Home() {
  return (
    <div className="home-page">
      <div className="hero-card">
        <h1 className="portal-title">Alliance University Course Registration Portal</h1>
        <p className="portal-subtitle">
          Welcome to the official online course registration portal. Explore semester elective and core courses, 
          verify prerequisites and credits, and register online with instant verification.
        </p>

        {/* Navigation Buttons using React Router's Link */}
        <div className="hero-actions">
          <Link to="/courses" className="btn btn-primary">
            View Courses
          </Link>
          <Link to="/register" className="btn btn-secondary">
            Register Now
          </Link>
        </div>
      </div>

      {/* Lab Features Highlight */}
      <div className="features-grid">
        <div className="feature-box">
          <h3>📚 Wide Course Catalog</h3>
          <p>Browse semester offerings across Computer Science, Data Structures, Networks, and Web Technologies.</p>
        </div>
        <div className="feature-box">
          <h3>⚡ Instant Validation</h3>
          <p>Client-side form validation prevents invalid submissions and guides you in real time.</p>
        </div>
        <div className="feature-box">
          <h3>📄 Instant Confirmation</h3>
          <p>Receive your submission confirmation immediately upon successful registration.</p>
        </div>
      </div>
    </div>
  );
}

export default Home;

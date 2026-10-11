import React from 'react';
import { Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import Home from './pages/Home';
import Courses from './pages/Courses';
import Register from './pages/Register';
import Success from './pages/Success';

function App() {
  return (
    <div className="app-container">
      {/* Persistent Navbar across all routes */}
      <Navbar />

      {/* Main Content Area containing routed views */}
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/courses" element={<Courses />} />
          <Route path="/register" element={<Register />} />
          <Route path="/success" element={<Success />} />
        </Routes>
      </main>

      {/* Simple College Footer */}
      <footer className="footer">
        <p>&copy; 2026 Alliance University - Academic Course Registration System</p>
      </footer>
    </div>
  );
}

export default App;

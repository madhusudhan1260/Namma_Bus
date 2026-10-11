import React from 'react';

// Reusable controlled input field component
function InputField({
  label,
  name,
  type = 'text',
  value,
  onChange,
  error,
  placeholder,
  required = true
}) {
  return (
    <div className="form-group">
      <label htmlFor={name} className="form-label">
        {label}
        {required && <span className="required-star">*</span>}
      </label>

      {/* Controlled input element */}
      <input
        id={name}
        name={name}
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className={`form-input ${error ? 'input-error' : ''}`}
      />

      {/* Conditionally rendered validation error message */}
      {error && <span className="error-message">{error}</span>}
    </div>
  );
}

export default InputField;

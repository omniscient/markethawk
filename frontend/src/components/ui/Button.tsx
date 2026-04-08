import React from 'react';
import { LucideIcon } from 'lucide-react';

interface ButtonProps {
  children?: React.ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  icon?: LucideIcon;
  loading?: boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  className?: string;
  type?: 'button' | 'submit' | 'reset';
  title?: string;
}

const Button: React.FC<ButtonProps> = ({
  children,
  onClick,
  variant = 'primary',
  size = 'md',
  icon: Icon,
  loading = false,
  disabled = false,
  fullWidth = false,
  className = '',
  type = 'button',
  title,
}) => {
  const baseClasses = 'inline-flex items-center justify-center font-medium rounded-lg transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-financial-dark';

  const variantClasses = {
    primary: 'bg-financial-blue text-white hover:bg-blue-600 focus:ring-blue-500 disabled:bg-blue-800 disabled:text-blue-300',
    secondary: 'bg-gray-700 text-gray-300 hover:bg-gray-600 focus:ring-gray-500 disabled:bg-gray-800 disabled:text-gray-500',
    danger: 'bg-red-600 text-white hover:bg-red-700 focus:ring-red-500 disabled:bg-red-800 disabled:text-red-300',
    ghost: 'text-gray-400 hover:text-white hover:bg-gray-700 focus:ring-gray-500 disabled:text-gray-600',
  };

  const sizeClasses = {
    sm: 'px-3 py-1.5 text-sm',
    md: 'px-4 py-2 text-sm',
    lg: 'px-6 py-3 text-base',
  };

  const classes = `${baseClasses} ${variantClasses[variant]} ${sizeClasses[size]} ${fullWidth ? 'w-full' : ''
    } ${className} ${disabled || loading ? 'cursor-not-allowed' : 'cursor-pointer'}`;

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={classes}
      title={title}
    >
      {loading && (
        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current mr-2"></div>
      )}
      {!loading && Icon && <Icon className="h-4 w-4 mr-2" />}
      {children}
    </button>
  );
};

export default Button;
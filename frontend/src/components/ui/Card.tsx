import React from 'react';
import { LucideIcon } from 'lucide-react';

interface CardProps {
  children: React.ReactNode;
  title?: string;
  icon?: LucideIcon;
  className?: string;
  actions?: React.ReactNode;
}

const Card: React.FC<CardProps> = ({ 
  children, 
  title, 
  icon: Icon, 
  className = '',
  actions 
}) => {
  return (
    <div className={`bg-financial-gray rounded-lg border border-gray-700 shadow-lg ${className}`}>
      {title && (
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <div className="flex items-center space-x-3">
            {Icon && <Icon className="h-5 w-5 text-financial-blue" />}
            <h3 className="text-lg font-semibold text-financial-light">{title}</h3>
          </div>
          {actions && <div>{actions}</div>}
        </div>
      )}
      <div className="p-6">
        {children}
      </div>
    </div>
  );
};

export default Card;
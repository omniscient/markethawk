import React from 'react';
import { LucideIcon } from 'lucide-react';

interface CardProps {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  icon?: LucideIcon;
  className?: string;
  actions?: React.ReactNode;
  noPadding?: boolean;
}

const Card: React.FC<CardProps> = ({ 
  children, 
  title, 
  subtitle,
  icon: Icon, 
  className = '',
  actions,
  noPadding = false
}) => {
  return (
    <div className={`bg-financial-gray rounded-lg border border-gray-700 shadow-lg ${className}`}>
      {title && (
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <div className="flex items-center space-x-3">
            {Icon && <Icon className="h-5 w-5 text-financial-blue" />}
            <div>
              <h3 className="text-lg font-semibold text-financial-light">{title}</h3>
              {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
            </div>
          </div>
          {actions && <div>{actions}</div>}
        </div>
      )}
      <div className={noPadding ? '' : 'p-6'}>
        {children}
      </div>
    </div>
  );
};

export default Card;
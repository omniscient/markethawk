import React from 'react';
import { Link } from 'react-router-dom';
import { Zap } from 'lucide-react';

interface TickerProps {
  ticker: string;
  assetClass?: string;
  showIcon?: boolean;
  className?: string;
  onClick?: (e: React.MouseEvent) => void;
  /** Whether to prevent the click from bubbling up to parent elements */
  stopPropagation?: boolean;
  /** Custom size styling, defaults to 'md' */
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  children?: React.ReactNode;
}

/**
 * A reusable component for rendering clickable stock tickers.
 * Consistently handles styling, navigation, and optional decorators like icons or badges.
 */
const Ticker: React.FC<TickerProps> = ({
  ticker,
  assetClass,
  showIcon = false,
  className = '',
  onClick,
  stopPropagation = true,
  size = 'md',
  children
}) => {
  const handleClick = (e: React.MouseEvent) => {
    if (stopPropagation) {
      e.stopPropagation();
    }
    if (onClick) {
      onClick(e);
    }
  };

  const getSizeClasses = () => {
    switch (size) {
      case 'xs': return 'text-[10px]';
      case 'sm': return 'text-xs';
      case 'md': return 'text-sm font-bold';
      case 'lg': return 'text-lg font-black';
      case 'xl': return 'text-xl font-black';
      default: return 'text-sm font-bold';
    }
  };

  const isFutures = assetClass?.toLowerCase() === 'futures' || assetClass?.toLowerCase() === 'fut';

  return (
    <Link
      to={`/stock/${ticker}`}
      onClick={handleClick}
      className={`inline-flex items-center text-financial-blue hover:text-blue-400 transition-colors group/ticker ${children ? '' : getSizeClasses()} ${className}`}
    >
      {children || (
        <>
          <span className="font-mono uppercase tracking-tight">{ticker}</span>
          
          {showIcon && (
            <Zap className="ml-1 h-3 w-3 text-yellow-400 opacity-0 group-hover/ticker:opacity-100 transition-opacity flex-shrink-0" />
          )}
          
          {isFutures && (
            <span className="ml-1.5 px-1 py-0.5 text-[9px] bg-financial-blue/20 text-financial-blue rounded leading-none uppercase font-bold flex-shrink-0">
              FUT
            </span>
          )}
        </>
      )}
    </Link>
  );
};

export default Ticker;

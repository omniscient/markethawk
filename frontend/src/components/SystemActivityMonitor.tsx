import React, { useState, useEffect, useRef } from 'react';
import { RefreshCw, Loader2, Wand2, Activity } from 'lucide-react';

interface SystemTask {
  id: string;
  type: string; // sync, analysis, normalization
  title: string;
  status: string;
}

export const SystemActivityMonitor: React.FC = () => {
  const [tasks, setTasks] = useState<SystemTask[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [_isConnected, setIsConnected] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: number;
    let isMounted = true;

    const connect = () => {
      if (!isMounted) return;
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      
      ws = new WebSocket(`${protocol}//${host}/api/system/ws/tasks`);

      ws.onopen = () => {
        if (!isMounted) {
            ws?.close();
            return;
        }
        setIsConnected(true);
      };
      
      ws.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const data = JSON.parse(event.data);
          if (data && Array.isArray(data.tasks)) {
            setTasks(data.tasks);
          }
        } catch (e) {
            console.error('Error parsing tasks WS data:', e);
        }
      };
      
      ws.onclose = () => {
        if (!isMounted) return;
        setIsConnected(false);
        reconnectTimer = window.setTimeout(connect, 3000);
      };
      
      ws.onerror = (err) => {
        // Suppress expected closing errors
        if (ws?.readyState !== WebSocket.CLOSED && ws?.readyState !== WebSocket.CLOSING) {
            console.error('Tasks WS error:', err);
        }
      };
    };

    connect();

    return () => {
      isMounted = false;
      window.clearTimeout(reconnectTimer);
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        // if still opening, close when it opens
        if (ws.readyState === WebSocket.CONNECTING) {
             ws.onopen = () => ws?.close();
        } else if (ws.readyState === WebSocket.OPEN) {
             ws.close();
        }
      }
    };
  }, []);

  // Click outside listener
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  if (tasks.length === 0) return null;

  return (
    <div className="relative flex items-center" ref={popoverRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center space-x-2 px-3 py-1.5 rounded-full border transition-all ${
            isOpen 
             ? 'bg-financial-blue/20 border-financial-blue text-blue-300 shadow-[0_0_10px_rgba(37,99,235,0.3)]' 
             : 'bg-gray-800 border-gray-700 text-blue-400 hover:bg-gray-700 hover:text-blue-300'
        } focus:outline-none`}
      >
        <Activity className="h-4 w-4 animate-pulse" />
        <span className="text-xs font-semibold tracking-wide uppercase">
            {tasks.length} Active
        </span>
      </button>

      {isOpen && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-gray-900 border border-gray-700 rounded-xl shadow-[0_10px_40px_rgba(0,0,0,0.5)] z-50 overflow-hidden backdrop-blur-md animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="px-4 py-3 bg-gray-800/80 border-b border-gray-700 flex justify-between items-center backdrop-blur-xl">
            <h3 className="font-semibold text-financial-light text-sm flex items-center space-x-2">
                <Loader2 className="w-4 h-4 text-financial-blue animate-spin" />
                <span>System Operations</span>
            </h3>
            <span className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">
                {tasks.length} task{tasks.length !== 1 ? 's' : ''}
            </span>
          </div>
          
          <div className="max-h-96 overflow-y-auto p-2 space-y-1.5 custom-scrollbar">
            {tasks.map(task => (
              <div key={task.id} className="flex gap-3 bg-gray-800/40 p-3 rounded-lg border border-gray-700/40 transition-colors hover:bg-gray-800/80">
                <div className="mt-0.5">
                    {task.type === 'sync' ? <RefreshCw className="h-4 w-4 text-blue-400 animate-spin" /> :
                     task.type === 'analysis' ? <Activity className="h-4 w-4 text-orange-400 animate-pulse" /> :
                     <Wand2 className="h-4 w-4 text-purple-400 animate-pulse" />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-gray-200 truncate">{task.title}</p>
                  <p className="text-[10px] text-gray-500 uppercase mt-0.5 font-bold tracking-wider">{task.status}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
export default SystemActivityMonitor;

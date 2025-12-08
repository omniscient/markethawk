import React, { useState } from 'react';
import {
  Bell,
  Plus,
  Edit,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Mail,
  Smartphone,
  Webhook
} from 'lucide-react';

// Components
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';

const Alerts: React.FC = () => {
  const [alerts, setAlerts] = useState([
    {
      id: '1',
      name: 'Pre-Market Volume Spike',
      type: 'volume_spike',
      isActive: true,
      conditions: 'Volume > 4x average AND Gap > 1%',
      deliveryMethod: 'email',
      lastTriggered: '2024-12-07 09:15'
    },
    {
      id: '2',
      name: 'Large Cap Breakout',
      type: 'price_movement',
      isActive: false,
      conditions: 'Price breaks resistance with volume',
      deliveryMethod: 'webhook',
      lastTriggered: '2024-12-06 14:30'
    },
    {
      id: '3',
      name: 'News Driven Volume',
      type: 'news',
      isActive: true,
      conditions: 'News + Volume spike > 2x',
      deliveryMethod: 'push',
      lastTriggered: '2024-12-07 08:45'
    }
  ]);

  const toggleAlert = (id: string) => {
    setAlerts(alerts.map(alert =>
      alert.id === id ? { ...alert, isActive: !alert.isActive } : alert
    ));
  };

  const getDeliveryIcon = (method: string) => {
    switch (method) {
      case 'email':
        return Mail;
      case 'push':
        return Smartphone;
      case 'webhook':
        return Webhook;
      default:
        return Bell;
    }
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case 'volume_spike':
        return 'bg-blue-500/20 text-blue-400';
      case 'price_movement':
        return 'bg-green-500/20 text-green-400';
      case 'news':
        return 'bg-yellow-500/20 text-yellow-400';
      default:
        return 'bg-gray-500/20 text-gray-400';
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-financial-light">Alert Configuration</h1>
          <p className="text-gray-400 mt-1">Manage your stock scanner alerts and notifications</p>
        </div>
        <Button variant="primary" icon={Plus}>
          Create Alert
        </Button>
      </div>

      {/* Alert Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <Card className="text-center">
          <div className="text-2xl font-bold text-financial-light">
            {alerts.filter(a => a.isActive).length}
          </div>
          <div className="text-sm text-gray-400">Active Alerts</div>
        </Card>
        <Card className="text-center">
          <div className="text-2xl font-bold text-positive">12</div>
          <div className="text-sm text-gray-400">Triggered Today</div>
        </Card>
        <Card className="text-center">
          <div className="text-2xl font-bold text-financial-blue">3</div>
          <div className="text-sm text-gray-400">Delivery Methods</div>
        </Card>
        <Card className="text-center">
          <div className="text-2xl font-bold text-financial-light">98.5%</div>
          <div className="text-sm text-gray-400">Delivery Rate</div>
        </Card>
      </div>

      {/* Alerts List */}
      <Card title="Configured Alerts" icon={Bell as any}>
        <div className="space-y-4">
          {alerts.map((alert) => {
            const DeliveryIcon = getDeliveryIcon(alert.deliveryMethod);
            return (
              <div
                key={alert.id}
                className="flex items-center justify-between p-4 bg-gray-800 rounded-lg hover:bg-gray-700 transition-colors"
              >
                <div className="flex items-center space-x-4">
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => toggleAlert(alert.id)}
                      className="text-gray-400 hover:text-white"
                    >
                      {alert.isActive ? (
                        <ToggleRight className="h-6 w-6 text-positive" />
                      ) : (
                        <ToggleLeft className="h-6 w-6 text-gray-500" />
                      )}
                    </button>
                  </div>

                  <div>
                    <h3 className="font-medium text-financial-light">{alert.name}</h3>
                    <p className="text-sm text-gray-400">{alert.conditions}</p>
                    <div className="flex items-center space-x-4 mt-2">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${getTypeColor(alert.type)}`}>
                        {alert.type.replace('_', ' ').toUpperCase()}
                      </span>
                      <div className="flex items-center space-x-1 text-xs text-gray-400">
                        <DeliveryIcon className="h-3 w-3" />
                        <span>{alert.deliveryMethod}</span>
                      </div>
                      <span className="text-xs text-gray-400">
                        Last: {alert.lastTriggered}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={Edit as any}
                    className="text-gray-400 hover:text-white"
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={Trash2 as any}
                    className="text-red-400 hover:text-red-300"
                  />
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* Notification Settings */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card title="Email Settings" icon={Mail}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Email Address
              </label>
              <input
                type="email"
                defaultValue="user@example.com"
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Frequency
              </label>
              <select className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue">
                <option>Immediate</option>
                <option>Every 5 minutes</option>
                <option>Every 15 minutes</option>
                <option>Hourly digest</option>
              </select>
            </div>
          </div>
        </Card>

        <Card title="Webhook Settings" icon={Webhook}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Webhook URL
              </label>
              <input
                type="url"
                placeholder="https://your-webhook-url.com"
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Secret Key
              </label>
              <input
                type="password"
                placeholder="Your webhook secret key"
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue"
              />
            </div>
            <Button variant="secondary" fullWidth>
              Test Webhook
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
};

export default Alerts;
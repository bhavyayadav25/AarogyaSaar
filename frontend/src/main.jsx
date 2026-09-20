import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { PatientPreferencesProvider } from './context/PatientPreferencesContext';
import GlobalErrorBoundary from './components/GlobalErrorBoundary';
import ProtectedRoute from './components/ProtectedRoute';
import RouteErrorBoundary from './components/RouteErrorBoundary';
import PatientLayout from './layouts/PatientLayout';
import DoctorLayout from './layouts/DoctorLayout';
import Landing from './pages/Landing';
import Login from './pages/Login';
import Register from './pages/Register';
import PatientHome from './pages/patient/Home';
import Visit from './pages/patient/Visit';
import Interview from './pages/patient/Interview';
import Ayush from './pages/patient/Ayush';
import AyushTransition from './pages/patient/AyushTransition';
import Documents from './pages/patient/Documents';
import Completion from './pages/patient/Completion';
import DoctorDashboard from './pages/doctor/Dashboard';
import DoctorConsultations from './pages/doctor/Consultations';
import DoctorEncounter from './pages/doctor/Encounter';
import AdminDashboard from './pages/admin/Dashboard';
import './styles/app.css';

function App(){return <Routes><Route path="/" element={<Landing/>}/><Route path="/login" element={<Login/>}/><Route path="/register" element={<Register/>}/><Route element={<ProtectedRoute role="patient"/>}><Route element={<PatientPreferencesProvider><RouteErrorBoundary homePath="/patient" title="Your patient workspace needs a fresh start." homeLabel="Return to patient home"><PatientLayout/></RouteErrorBoundary></PatientPreferencesProvider>}><Route path="/patient" element={<PatientHome/>}/><Route path="/patient/visit" element={<Visit/>}/><Route path="/patient/interview" element={<Interview/>}/><Route path="/patient/ayush-transition" element={<AyushTransition/>}/><Route path="/patient/ayush" element={<Ayush/>}/><Route path="/patient/documents" element={<Documents/>}/><Route path="/patient/completion" element={<Completion/>}/></Route></Route><Route element={<ProtectedRoute role="doctor"/>}><Route element={<RouteErrorBoundary homePath="/doctor" title="Your doctor workspace needs a fresh start." homeLabel="Return to doctor queue"><DoctorLayout/></RouteErrorBoundary>}><Route path="/doctor" element={<DoctorDashboard/>}/><Route path="/doctor/consultations" element={<DoctorConsultations/>}/><Route path="/doctor/encounter/:encounterId" element={<DoctorEncounter/>}/></Route></Route><Route element={<ProtectedRoute role="admin"/>}><Route path="/admin" element={<RouteErrorBoundary homePath="/admin" title="The hospital workspace needs a fresh start." homeLabel="Return to hospital dashboard"><AdminDashboard/></RouteErrorBoundary>}/></Route><Route path="*" element={<Navigate to="/" replace/>}/></Routes>}
ReactDOM.createRoot(document.getElementById('root')).render(<React.StrictMode><GlobalErrorBoundary><BrowserRouter><AuthProvider><App/></AuthProvider></BrowserRouter></GlobalErrorBoundary></React.StrictMode>);

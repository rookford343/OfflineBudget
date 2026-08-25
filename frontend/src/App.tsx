import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { isAuthenticated } from "./store/auth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import Dashboard from "./pages/Dashboard";
import CreditCards from "./pages/CreditCards";
import Forecast from "./pages/Forecast";
import Spending from "./pages/Spending";
import Recurring from "./pages/Recurring";
import Transactions from "./pages/Transactions";
import Budget from "./pages/Budget";
import Settings from "./pages/Settings";
import Import from "./pages/Import";
import Calendar from "./pages/Calendar";
import Goals from "./pages/Goals";
import NetWorth from "./pages/NetWorth";
import AccountDetail from "./pages/AccountDetail";

function PrivateRoute({ children }: { children: React.ReactNode }) {
  return isAuthenticated() ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route
          path="/"
          element={
            <PrivateRoute>
              <Layout />
            </PrivateRoute>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="goals" element={<Goals />} />
          <Route path="net-worth" element={<NetWorth />} />
          <Route path="calendar" element={<Calendar />} />
          <Route path="credit-cards" element={<CreditCards />} />
          <Route path="forecast" element={<Forecast />} />
          <Route path="spending" element={<Spending />} />
          <Route path="recurring" element={<Recurring />} />
          <Route path="transactions" element={<Transactions />} />
          <Route path="accounts/:id" element={<AccountDetail />} />
          <Route path="import" element={<Import />} />
          <Route path="budget" element={<Budget />} />
          <Route path="settings/*" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import Today from "./pages/Today";
import Profile from "./pages/Profile";
import Login from "./pages/Login";
import Consent from "./pages/Consent";
import Account from "./pages/Account";
import { AuthProvider } from "./lib/auth";
import { RequireAuth } from "./components/RequireAuth";
import "./index.css";

const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <App />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Today /> },
      { path: "consent", element: <Consent /> },
      { path: "profile", element: <Profile /> },
      { path: "account", element: <Account /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </React.StrictMode>
);

import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import Coverage from "./pages/Coverage";
import Stories from "./pages/Stories";
import Editor from "./pages/Editor";
import { AuthProvider } from "./lib/auth";
import "./index.css";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Coverage /> },
      { path: "stories", element: <Stories /> },
      { path: "new", element: <Editor /> },
      { path: "story/:id", element: <Editor /> },
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

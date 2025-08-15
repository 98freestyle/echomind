import React, { useContext } from "react";
import { AuthContext } from "../context/AuthContext.jsx";

export default function Dashboard() {
    const { user } = useContext(AuthContext);

    return (
        <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center">
            <h1 className="text-3xl font-bold mb-4">Welcome, {user.email} 👋</h1>
            <p className="text-gray-400">You’re logged in and seeing a protected page.</p>
        </div>
    );
}

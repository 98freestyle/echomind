import React, { useState, useContext } from "react";
import axios from "axios";
import { AuthContext } from "../context/AuthContext.jsx";

export default function Login() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [success, setSuccess] = useState(false);

    const { login } = useContext(AuthContext);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError("");
        setSuccess(false);

        try {
            const res = await axios.post("http://127.0.0.1:5000/login", {
                email,
                password
            });

            if (res.data.success) {
                login(email); // ✅ Save user state
                setSuccess(true);
                setEmail("");
                setPassword("");
            }
        } catch (err) {
            setError(err.response?.data?.error || "Login failed.");
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-black text-white px-4">
            <form
                onSubmit={handleSubmit}
                className="bg-gray-800 p-8 rounded-lg w-full max-w-md space-y-4 shadow-lg"
            >
                <h2 className="text-2xl font-bold text-center">Login</h2>

                {error && <div className="bg-red-600 p-2 rounded text-sm">{error}</div>}
                {success && (
                    <div className="bg-green-600 p-2 rounded text-sm">
                        Logged in successfully! ✅
                    </div>
                )}

                <input
                    type="email"
                    placeholder="Email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full p-2 bg-gray-900 rounded"
                />
                <input
                    type="password"
                    placeholder="Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full p-2 bg-gray-900 rounded"
                />

                <button
                    type="submit"
                    className="w-full bg-indigo-600 hover:bg-indigo-700 p-2 rounded font-semibold"
                >
                    Login
                </button>
            </form>
        </div>
    );
}

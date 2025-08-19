import React, { useState } from "react";
import axios from "axios";
import { useParams, useNavigate } from "react-router-dom";

export default function ResetPasswordConfirm() {
    const { token } = useParams();
    const navigate = useNavigate();
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [error, setError] = useState("");
    const [message, setMessage] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError("");
        setMessage("");

        if (newPassword !== confirmPassword) {
            setError("Passwords do not match.");
            return;
        }

        if (newPassword.length < 6) {
            setError("Password must be at least 6 characters.");
            return;
        }

        setLoading(true);

        try {
            const res = await axios.post(`http://127.0.0.1:5000/reset-password-confirm/${token}`, {
                new_password: newPassword
            });

            if (res.data.success) {
                setMessage("Password reset successfully!");
                setTimeout(() => navigate("/login"), 2000);
            } else {
                setError("Invalid or expired token.");
            }
        } catch (err) {
            setError(err.response?.data?.error || "Reset failed.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-black text-white px-4">
            <form onSubmit={handleSubmit} className="bg-gray-800 p-8 rounded-lg w-full max-w-md space-y-4 shadow-lg">
                <h2 className="text-2xl font-bold text-center">Set New Password</h2>

                {error && <div className="bg-red-600 p-2 rounded text-sm">{error}</div>}
                {message && <div className="bg-green-600 p-2 rounded text-sm">{message}</div>}

                <input
                    type="password"
                    placeholder="New Password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="w-full p-2 bg-gray-900 rounded"
                    required
                />
                <input
                    type="password"
                    placeholder="Confirm New Password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="w-full p-2 bg-gray-900 rounded"
                    required
                />

                <button
                    type="submit"
                    disabled={loading}
                    className={`w-full bg-indigo-600 p-2 rounded font-semibold transition ${loading ? "opacity-50 cursor-not-allowed" : "hover:bg-indigo-700"
                        }`}
                >
                    {loading ? "Resetting..." : "Reset Password"}
                </button>
            </form>
        </div>
    );
}

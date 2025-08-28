import React, { createContext, useState, useEffect, useCallback } from "react";

export const AuthContext = createContext();

function toBool(v) {
    return v === true || v === "true" || v === 1 || v === "1";
}

export function AuthProvider({ children }) {
    // Load once from localStorage
    const [user, setUser] = useState(() => {
        try {
            const stored = localStorage.getItem("user");
            return stored ? JSON.parse(stored) : null;
        } catch {
            return null;
        }
    });

    // Persist helper (keeps state + localStorage in sync)
    const persist = useCallback((u) => {
        setUser(u);
        try {
            localStorage.setItem("user", JSON.stringify(u));
        } catch { }
    }, []);

    // Login accepts either boolean or string/number; coerces to real boolean
    const login = (email, is_premium = false) => {
        persist({ email, is_premium: toBool(is_premium) });
    };

    const logout = () => {
        setUser(null);
        try {
            localStorage.removeItem("user");
        } catch { }
    };

    // Hydrate premium flag from backend so Navbar matches real account state
    useEffect(() => {
        let aborted = false;
        async function hydrate() {
            if (!user?.email) return;
            try {
                const res = await fetch("/usage", {
                    headers: { "X-User-Email": user.email },
                    credentials: "include",
                });
                if (!res.ok) return;
                const data = await res.json();
                const premium = toBool(data?.is_premium ?? data?.isPremium);
                if (!aborted && typeof premium !== "undefined" && premium !== toBool(user.is_premium)) {
                    persist({ email: user.email, is_premium: premium });
                }
            } catch {
                // ignore network errors
            }
        }
        hydrate();
        return () => {
            aborted = true;
        };
    }, [user?.email, persist]);

    // Keep state in sync if another tab updates localStorage
    useEffect(() => {
        function onStorage(e) {
            if (e.key !== "user") return;
            try {
                const next = e.newValue ? JSON.parse(e.newValue) : null;
                setUser(next);
            } catch { }
        }
        window.addEventListener("storage", onStorage);
        return () => window.removeEventListener("storage", onStorage);
    }, []);

    return (
        <AuthContext.Provider value={{ user, setUser: persist, login, logout }}>
            {children}
        </AuthContext.Provider>
    );
}

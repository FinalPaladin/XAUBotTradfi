const AUTH_KEY = "xaubot_auth";
const VALID_USER = "admin";
const VALID_PASSWORD = "123qwe";

export function login(username: string, password: string): boolean {
  if (username === VALID_USER && password === VALID_PASSWORD) {
    sessionStorage.setItem(AUTH_KEY, username);
    return true;
  }
  return false;
}

export function logout() {
  sessionStorage.removeItem(AUTH_KEY);
}

export function isAuthenticated(): boolean {
  return sessionStorage.getItem(AUTH_KEY) === VALID_USER;
}

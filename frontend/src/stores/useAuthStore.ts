import { create } from "zustand";

interface UsersMeResponse {
  id: string;
  user_id: number;
  group_id: number;
  group_name: string;
  email: string;
  user_name: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
  is_groupadmin: boolean;
  is_manager: boolean;
}

interface AuthState extends UsersMeResponse {
  isLogged: boolean;
  setLoggedUser: (data: UsersMeResponse) => void;
  clearLoggedUser: () => void;
}

const defaultValues: Omit<AuthState, "setLoggedUser" | "clearLoggedUser"> = {
  isLogged: false,
  id: "",
  user_id: -1,
  group_id: -1,
  group_name: "",
  email: "",
  user_name: "",
  full_name: "",
  is_active: false,
  is_superuser: false,
  is_verified: false,
  is_groupadmin: false,
  is_manager: false,
};

export const useAuthStore = create<AuthState>((set) => ({
  ...defaultValues,
  setLoggedUser: (data) => set({ ...data, isLogged: true }),
  clearLoggedUser: () => set(defaultValues),
}));

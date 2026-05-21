import { UserInfoI } from '../../app/interfaces/userinfo-i';

export const mockUser: UserInfoI = {
  provider_id: 'mock-provider-1',
  email: 'wouhou@lmddc.lu',
  name: 'Best Designer',
  role: 'user',
  id: 'mock-user-1',
  is_active: true,
};

export const mockAdminUser: UserInfoI = {
  provider_id: 'mock-provider-2',
  email: 'admin@example.com',
  name: 'Admin',
  role: 'admin',
  id: 'mock-admin-1',
  is_active: true,
};

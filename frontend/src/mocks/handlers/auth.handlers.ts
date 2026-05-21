import { http, HttpResponse } from 'msw';
import { environment } from '../../environments/environment';
import { mockUser } from '../fixtures/user.fixture';

const api = environment.apiBaseUrl;

export const authHandlers = [
  http.get(`${api}/oauth/user_info`, () => HttpResponse.json(mockUser)),
  http.post(`${api}/oauth/refresh`, () => HttpResponse.json({ ok: true })),
  http.get(`${api}/oauth/logout`, () => HttpResponse.json({ ok: true })),
];

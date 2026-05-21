import { Routes } from '@angular/router';
import { authGuard } from './guard/auth.guard';
import { adminGuard } from './guard/admin.guard';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./components/pages/welcome/welcome.component').then(
        (m) => m.WelcomeComponent
      ),
  },
  {
    path: 'dashboard',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./components/pages/dashboard/dashboard.component').then(
        (m) => m.DashboardComponent
      ),
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./components/features/overview/overview.component').then(
            (m) => m.OverviewComponent
          ),
      },
      {
        path: 'edit/:id',
        loadComponent: () =>
          import(
            './components/features/edit-chatbot/edit-chatbot.component'
          ).then((m) => m.EditChatbotComponent),
      },
      {
        path: 'new',
        loadComponent: () =>
          import(
            './components/features/new-chatbot/new-chatbot.component'
          ).then((m) => m.NewChatbotComponent),
      },
    ],
  },
  {
    path: 'chat/:id',
    loadComponent: () =>
      import('./components/pages/chat/chat.component').then(
        (m) => m.ChatComponent
      ),
  },
  {
    path: 'admin',
    canActivate: [adminGuard],
    children: [
      {
        path: '',
        loadComponent: () =>
          import(
            './components/pages/admin/admin-dashboard/admin-dashboard.component'
          ).then((m) => m.AdminDashboardComponent),
      },
      {
        path: 'jobs',
        loadComponent: () =>
          import('./components/pages/admin/admin-jobs/admin-jobs.component').then(
            (m) => m.AdminJobsComponent
          ),
      },
      {
        path: 'jobs/:id',
        loadComponent: () =>
          import(
            './components/pages/admin/admin-job-detail/admin-job-detail.component'
          ).then((m) => m.AdminJobDetailComponent),
      },
    ],
  },
];

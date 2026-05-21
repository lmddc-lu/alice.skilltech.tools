import { ChangeDetectionStrategy, Component } from '@angular/core';
import { HeaderComponent } from '../../shared/layout/header/header.component';
import { RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-dashboard',
  imports: [HeaderComponent, RouterOutlet],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent {}

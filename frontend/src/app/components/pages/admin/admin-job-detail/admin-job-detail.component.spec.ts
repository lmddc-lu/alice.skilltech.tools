import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AdminJobDetailComponent } from './admin-job-detail.component';

describe('AdminJobDetailComponent', () => {
  let component: AdminJobDetailComponent;
  let fixture: ComponentFixture<AdminJobDetailComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AdminJobDetailComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(AdminJobDetailComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

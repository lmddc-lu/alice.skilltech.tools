import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ReviewConfirmStepComponent } from './review-confirm-step.component';

describe('ReviewConfirmStepComponent', () => {
  let component: ReviewConfirmStepComponent;
  let fixture: ComponentFixture<ReviewConfirmStepComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ReviewConfirmStepComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ReviewConfirmStepComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

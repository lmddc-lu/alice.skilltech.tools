import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CourseSelectionStepComponent } from './course-selection-step.component';

describe('CourseSelectionStepComponent', () => {
  let component: CourseSelectionStepComponent;
  let fixture: ComponentFixture<CourseSelectionStepComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CourseSelectionStepComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(CourseSelectionStepComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

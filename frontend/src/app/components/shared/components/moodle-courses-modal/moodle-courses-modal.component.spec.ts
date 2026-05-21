import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MoodleCoursesModalComponent } from './moodle-courses-modal.component';

describe('MoodleCoursesModalComponent', () => {
  let component: MoodleCoursesModalComponent;
  let fixture: ComponentFixture<MoodleCoursesModalComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MoodleCoursesModalComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(MoodleCoursesModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

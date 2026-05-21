import { TestBed } from '@angular/core/testing';

import { MoodleCoursesService } from './moodle-courses.service';

describe('MoodleCoursesService', () => {
  let service: MoodleCoursesService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(MoodleCoursesService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});

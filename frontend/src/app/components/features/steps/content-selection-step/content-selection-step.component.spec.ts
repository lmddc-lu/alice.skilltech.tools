import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ContentSelectionStepComponent } from './content-selection-step.component';

describe('ContentSelectionStepComponent', () => {
  let component: ContentSelectionStepComponent;
  let fixture: ComponentFixture<ContentSelectionStepComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ContentSelectionStepComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ContentSelectionStepComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

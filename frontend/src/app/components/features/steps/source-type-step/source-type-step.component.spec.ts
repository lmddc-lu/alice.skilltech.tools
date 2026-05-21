import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SourceTypeStepComponent } from './source-type-step.component';

describe('SourceTypeStepComponent', () => {
  let component: SourceTypeStepComponent;
  let fixture: ComponentFixture<SourceTypeStepComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SourceTypeStepComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(SourceTypeStepComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

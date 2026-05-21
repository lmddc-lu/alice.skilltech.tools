import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ChatbotConfigStepComponent } from './chatbot-config-step.component';

describe('ChatbotConfigStepComponent', () => {
  let component: ChatbotConfigStepComponent;
  let fixture: ComponentFixture<ChatbotConfigStepComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ChatbotConfigStepComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ChatbotConfigStepComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

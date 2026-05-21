import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ChatbotListComponent } from './chatbot-list.component';

describe('ChatbotListComponent', () => {
  let component: ChatbotListComponent;
  let fixture: ComponentFixture<ChatbotListComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ChatbotListComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ChatbotListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
